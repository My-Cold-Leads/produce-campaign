#!/usr/bin/env bash
# Prove scripts/check-copy-variation.py goes RED on repeated copy and GREEN on varied copy.
# A check that has never failed on bad input may be doing nothing. Run:
#   bash scripts/tests/test-check-copy-variation.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
GATE=scripts/check-copy-variation.py
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0

python3 - "$TMP" <<'PY'
import json, sys
out = sys.argv[1]
SIG = "Nombre Apellido<br>Empresa Ejemplo"
END = "<br><div>Un saludo,</div><div>%signature%</div>"
def fixture(name, variants):
    leads = []
    for i in range(60):
        f = {"company": "Empresa %d" % i, "first_name": " Nombre%d" % i}
        for label, tpl, w in variants:
            body = tpl
            for k, v in f.items():
                body = body.replace("{{%s}}" % k, v)
            leads.append({"custom_fields": f, "weight": w, "variant": label, "template": tpl,
                          "body": body.replace("%signature%", SIG)})
    json.dump({"campaign": name, "signature": SIG,
               "sequences": [{"id": "E1", "template": variants[0][1], "leads": leads}]},
              open("%s/%s.json" % (out, name), "w"))
TAIL = "<br><div>Además {una|otra|alguna} cosa {breve|corta|rápida} y {útil|clara|simple} al final.</div>"
fixture("varied", [(l, "<div>{Hola|Buenos días}{{first_name}},</div><br><div>%s {opción|forma|manera} sobre {{company}} y su zona.</div>%s%s" % (p, TAIL, END), 1/3)
                   for l, p in (("A", "Primera"), ("B", "Segunda"), ("C", "Tercera"))])
fixture("shared_line", [(l, "<div>{Hola|Buenos días}{{first_name}},</div><br><div>La misma frase {repetida|idéntica} para todos.</div>" + TAIL + END, 1/3) for l in "ABC"])
fixture("fixed_line", [("A", "<div>{Hola|Buenos días}{{first_name}},</div><br><div>Esta frase no cambia nunca para nadie.</div>" + TAIL + END, 1.0)])
# A French greeting the default (Spanish/English) patterns do not know, so it counts as a fixed body line.
fixture("fr_greeting", [(l, "<div>Bonjour{{first_name}},</div><br><div>%s {option|façon|manière} pour {{company}} et sa région.</div>%s%s" % (p, TAIL, END), 1/3)
                        for l, p in (("A", "Première"), ("B", "Deuxième"), ("C", "Troisième"))])
PY

check() {  # $1=fixture $2=expected PASS|FAIL $3=required text when FAIL $4=optional extra flag
  out=$(python3 "$GATE" --rendered "$TMP/$1.json" --client test --small-cohort-ack "test fixture" --out-dir "$TMP" ${4:+"$4"} ${5:+"$5"} 2>&1); code=$?
  got=PASS; [ $code -ne 0 ] && got=FAIL
  if [ "$got" = "$2" ] && { [ "$got" = PASS ] || grep -q "$3" <<<"$out"; }; then
    echo "  ok   $1 -> $got"; pass=$((pass+1))
  else
    echo "  FAIL $1 expected $2 got $got"; echo "$out" | head -6; fail=$((fail+1))
  fi
}

check varied PASS ""                        # each variant's own line reaches ~11%
check shared_line FAIL max_line_share       # same 2-option line for everyone = 50%
check fixed_line FAIL fixed_body_lines      # a line that never changes
check fr_greeting FAIL fixed_body_lines     # default patterns do not know "Bonjour"
check fr_greeting PASS "" --exclusions '{"greeting": "^bonjour\\b[^.!?,]{0,30}$"}'  # override for your language

echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
