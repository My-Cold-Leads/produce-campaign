#!/usr/bin/env bash
# Prove scripts/check-copy-variation.py goes RED on repeated copy and GREEN on varied copy.
# A check that has never failed on bad input may be doing nothing. Run:
#   bash scripts/tests/test-check-copy-variation.sh
set -uo pipefail
cd "$(dirname "$0")/../.." || exit 1
GATE=${GATE:-scripts/check-copy-variation.py}   # point GATE at an older copy to watch the newer fixtures go red
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0

python3 - "$TMP" <<'PY'
import json, sys
out = sys.argv[1]
SIG = "Nombre Apellido<br>Empresa Ejemplo"
END = "<br><div>Un saludo,</div><div>%signature%</div>"
def fixture(name, variants, extra=None):
    leads = []
    for i in range(60):
        f = {"company": "Empresa %d" % i, "first_name": " Nombre%d" % i}
        for label, tpl, w in variants:
            body = tpl
            for k, v in f.items():
                body = body.replace("{{%s}}" % k, v)
            leads.append({"custom_fields": f, "weight": w, "variant": label, "template": tpl,
                          "body": body.replace("%signature%", SIG)})
    doc = {"campaign": name, "signature": SIG,
           "sequences": [{"id": "E1", "template": variants[0][1], "leads": leads}]}
    doc.update(extra or {})
    json.dump(doc,
              open("%s/%s.json" % (out, name), "w"))
TAIL = "<br><div>Además {una|otra|alguna} cosa {breve|corta|rápida} y {útil|clara|simple} al final.</div>"
fixture("varied", [(l, "<div>{Hola|Buenos días}{{first_name}},</div><br><div>%s {opción|forma|manera} sobre {{company}} y su zona.</div>%s%s" % (p, TAIL, END), 1/3)
                   for l, p in (("A", "Primera"), ("B", "Segunda"), ("C", "Tercera"))])
fixture("shared_line", [(l, "<div>{Hola|Buenos días}{{first_name}},</div><br><div>La misma frase {repetida|idéntica} para todos.</div>" + TAIL + END, 1/3) for l in "ABC"])
fixture("fixed_line", [("A", "<div>{Hola|Buenos días}{{first_name}},</div><br><div>Esta frase no cambia nunca para nadie.</div>" + TAIL + END, 1.0)])
# A French greeting the default (Spanish/English) patterns do not know, so it counts as a fixed body line.
fixture("fr_greeting", [(l, "<div>Bonjour{{first_name}},</div><br><div>%s {option|façon|manière} pour {{company}} et sa région.</div>%s%s" % (p, TAIL, END), 1/3)
                        for l, p in (("A", "Première"), ("B", "Deuxième"), ("C", "Troisième"))])
# English sign-off, "Hola, name." greeting with a comma, and a sender-token-only line. None of these
# is body copy; each used to be scored as a fixed line.
BODY = "<br><div>%s {opción|forma|manera} sobre {{company}} y su zona.</div>" + TAIL
ABC = (("A", "Primera"), ("B", "Segunda"), ("C", "Tercera"))
for name, close in (("en_signoff", "Best regards"), ("en_thanks", "Many thanks"), ("en_cheers", "Cheers")):
    fixture(name, [(l, "<div>{Hi|Hello}{{first_name}},</div>" + BODY % p + "<br><div>%s,</div><div>%%signature%%</div>" % close, 1/3) for l, p in ABC])
fixture("greeting_comma", [(l, "<div>Hola,{{first_name}}.</div>" + BODY % p + END, 1/3) for l, p in ABC])
fixture("sender_token", [(l, "<div>{Hola|Buenos días}{{first_name}},</div>" + BODY % p + "<br><div>Un saludo,</div><div>%sender-name%</div>", 1/3) for l, p in ABC])
# The exemptions must stay narrow: the same words inside a sentence are still measured.
fixture("signoff_in_sentence", [(l, "<div>{Hola|Buenos días}{{first_name}},</div>" + BODY % p + "<br><div>Cheers for the help so far</div>" + END, 1/3) for l, p in ABC])
fixture("sender_token_in_sentence", [(l, "<div>{Hola|Buenos días}{{first_name}},</div>" + BODY % p + "<br><div>Soy %sender-firstname% y llevo este tema aquí.</div>" + END, 1/3) for l, p in ABC])
fixture("greeting_comma_sentence", [(l, "<div>Buenas noticias, este año abrimos un grupo nuevo.</div>" + BODY % p + END, 1/3) for l, p in ABC])
# Closing block: a short brand line right after the sign-off is exempt, a sentence there is not.
fixture("closing_block", [(l, "<div>{Hola|Buenos días}{{first_name}},</div>" + BODY % p + "<br><div>Un saludo,</div><div>%sender-name%</div><div>Acme Logistics</div>", 1/3) for l, p in ABC])
fixture("closing_sentence", [(l, "<div>{Hola|Buenos días}{{first_name}},</div>" + BODY % p + "<br><div>Un saludo,</div><div>Reserva una llamada con nosotros aquí</div>", 1/3) for l, p in ABC])
# A short field that carries copy: masked (and reported as one fixed line) unless declared.
leads = []
for i in range(60):
    f = {"company": "Empresa %d" % i, "first_name": " Nombre%d" % i, "intro": ["Soy", "Te escribe", "Aquí", "Le escribe", "Habla", "Escribe", "Te saluda", "Le saluda"][i % 8]}
    leads.append({"custom_fields": f})
json.dump({"campaign": "copy_field", "signature": SIG, "sequences": [{"id": "E1",
           "template": "<div>{Hola|Buenos días}{{first_name}},</div><br><div>{{intro}} %sender-firstname%</div><br><div>{Una|Otra|Alguna} {opción|forma|manera} {breve|corta|rápida} sobre {{company}} y su zona.</div>" + TAIL + END,
           "leads": leads}]}, open("%s/copy_field.json" % out, "w"))
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

check en_signoff PASS ""                    # "Best regards," is a sign-off, not body copy
check en_thanks PASS ""
check en_cheers PASS ""
check greeting_comma PASS ""                # "Hola, Ana." is a greeting
check sender_token PASS ""                  # a line that is only %sender-name%
check signoff_in_sentence FAIL max_line_share      # "Cheers for the help so far" is still body copy
check sender_token_in_sentence FAIL max_line_share # words around the token are still measured
check greeting_comma_sentence FAIL max_line_share  # "Buenas noticias, este año..." is still body copy
check closing_block PASS ""                 # short brand line straight after the sign-off
check closing_sentence FAIL fixed_body_lines       # a sentence after the sign-off is measured
check copy_field FAIL fixed_body_lines             # undeclared copy field is masked into one fixed line
check copy_field PASS "" --copy-field intro        # declared: measured, 8 renderings
check copy_field FAIL "declaration refused" --copy-field company  # lead data cannot be declared copy

if python3 "$GATE" --self-test >/dev/null 2>&1; then echo "  ok   --self-test"; pass=$((pass+1)); else echo "  FAIL --self-test"; fail=$((fail+1)); fi

echo "passed $pass, failed $fail"
[ "$fail" -eq 0 ]
