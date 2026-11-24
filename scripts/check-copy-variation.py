#!/usr/bin/env python3
"""Check that no sentence repeats across too many of your outgoing cold emails.

Measures the FINAL emails (custom fields filled in, spintax expanded) and fails when:
  - any body line reaches more than 15% of recipients (after spintax branching), or
  - any body line is identical for the whole cohort (a fixed line), or
  - fewer than 90% of the emails are distinct from each other.

Not measured, because they are the same for everyone by design: greetings ("Hola Ana,",
"Hola, Ana.", "Dear Ana,"), sign-offs (Spanish and English), the inbox signature, unsubscribe
lines, URL-only lines, a line that is only a %sender-...% token, and up to two short
name/brand lines directly after the sign-off (the closing block).

Inputs:
  --rendered file.json   a JSON file with your templates and per-lead fields (works before you send)
  --campaign ID          read a live Smartlead campaign (needs SMARTLEAD_API_KEY in the environment)
  --copy-field NAME      a short custom field that carries copy (not lead data); it is then
                         measured instead of masked. Refused above 24 distinct values.
  --self-test            run the built-in red/green fixtures and exit

A sequence with a template but no leads yet is measured in template-only mode (line share and
fixed lines only). Template spintax shares are expected values under uniform branch selection,
not observed sends.
"""
import argparse
import datetime as dt
import hashlib
import html
import json
import math
import os
import re
import sys
import time
import urllib.request


MAX_LINE_SHARE = 0.15
MIN_DISTINCT_SHARE = 0.90
MIN_COHORT = 20


# A greeting is a greeting word plus at most a short name. One optional comma straight after
# the word covers the "Hola, Ana." style; any other comma or sentence punctuation means the
# line is body copy ("Buenas noticias, este año...") and stays measured.
GREETING_RE = re.compile(

    r"^(hola|buenas|buenos días|buenas tardes|buenas noches|qué tal|que tal|hello|hi|hey|dear)"

    r"\b,?[^.!?¿¡,]{0,30}$", re.I)


# Fully anchored: only a line that IS the closing matches. "Cheers for the help" is body copy.
SIGNOFF_RE = re.compile(
    r"^(un saludo|saludos|un abrazo|un fuerte abrazo|un cordial saludo|gracias|best|"
    r"kind regards|atentamente|best regards|warm regards|regards|all the best|best wishes|"
    r"thanks|thank you|many thanks|cheers|"
    r"espero que (sirva|os sirva|te sirva|ayude|os ayude)|"
    r"que (te vaya bien|vaya todo bien)|[a-záéíóúñ]+,)$", re.I)
UNSUB_RE = re.compile(r"(unsubscribe|cancelar suscripción|darse de baja|dar(?:se|te|os)? de baja|no recibir|dejar de recibir|responder .?baja)", re.I)


# A line that is nothing but a sender-identity token is resolved per inbox at send time, like
# %signature%. "Thanks, %sender-name%" keeps its words and is measured as body copy.
SENDER_TOKEN_RE = re.compile(r"^%sender-(?:name|firstname|lastname)%$", re.I)


URL_ONLY_LINE_RE = re.compile(r"^https?://\S+$", re.I)
VAR_RE = re.compile(r"\{\{\s*([^} ]+)\s*\}\}")


def plain(value):
    value = html.unescape(value or "")
    value = re.sub(r"<(?:br|/div|/p|/li)\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return value.replace("\r\n", "\n").replace("\r", "\n")


MERGE_TOKEN_MAX_SHARE = 0.25


# A declared copy field comes from a small approved set. More distinct values than this means
# it is lead data, and the declaration is refused so the mask cannot be dodged.
COPY_FIELD_MAX_DISTINCT = 24


OWN_LINE_RE_CACHE = {}


def occupies_own_line(text, value):
    """True when `value` sits alone as a whole block/line of the body"""
    if not value.strip():
        return False
    pat = OWN_LINE_RE_CACHE.get(value)
    if pat is None:
        v = re.escape(value.strip())

        pat = re.compile(
            r"(?:<(?:div|p)[^>]*>|<br\s*/?>|\A|\n)\s*" + v + r"\s*(?:</(?:div|p)>|<br\s*/?>|\Z|\n)",
            re.I)
        OWN_LINE_RE_CACHE[value] = pat
    return bool(pat.search(text))


def mask_values(text, fields, copy_fields=()):
    """Mask a lead's own MERGE TOKENS before any metric is calculated"""
    for key, value in mask_plan(text, fields, copy_fields):
        text = re.sub(re.escape(value), "[[VAR:%s]]" % key, text, flags=re.I)
    return text


def mask_plan(text, fields, copy_fields=()):
    """Decide WHICH field values mask_values would mask, without mutating anything"""
    body_len = max(1, len(text))
    copy_fields = {str(x) for x in (copy_fields or ())}
    values = [(str(k), str(v)) for k, v in (fields or {}).items() if str(v).strip()]
    plan = []
    for key, value in sorted(values, key=lambda item: len(item[1]), reverse=True):
        if key in copy_fields:
            continue
        if len(value) / body_len >= MERGE_TOKEN_MAX_SHARE:
            continue
        if occupies_own_line(text, value):
            continue
        if len(value) < 3:
            continue
        plan.append((key, value))
    return plan


# Lines are split on the UNMASKED body first and masked one by one. Masking the whole body and
# then splitting can drop a line break that sits inside a field value, which shifts every later
# line by one and classifies it against its neighbour's text.
def mask_line(line, plan):
    """Apply an already-decided mask_plan to ONE already-split, already-plain line"""
    for key, value in plan:
        line = re.sub(re.escape(value), "[[VAR:%s]]" % key, line, flags=re.I)
    return line


def substitute(template, fields):
    return VAR_RE.sub(lambda m: str((fields or {}).get(m.group(1), m.group(0))), template or "")


def spin_shape(text):
    """Return a non-enumerated spintax shape and its number of uniform states"""
    states = 1
    out = []
    i = 0
    while i < len(text):
        if text[i] != "{":
            out.append(text[i]); i += 1; continue
        end = text.find("}", i + 1)
        if end < 0 or "|" not in text[i + 1:end]:
            out.append(text[i]); i += 1; continue
        branches = text[i + 1:end].split("|")
        states *= len(branches)
        out.append("<SPIN:%d>" % len(branches))
        i = end + 1
    return "".join(out), states


def collapse_first(text):
    """Collapse each spintax block to its first branch - FOR CLASSIFICATION ONLY"""
    out, i = [], 0
    while i < len(text):
        if text[i] != "{":
            out.append(text[i]); i += 1; continue
        end = text.find("}", i + 1)
        if end < 0 or "|" not in text[i + 1:end]:
            out.append(text[i]); i += 1; continue
        out.append(text[i + 1:end].split("|")[0])
        i = end + 1
    return "".join(out)


def content_class(line, allowlist, sig_lines=(), raw=None):
    if line in allowlist:
        return "allowlist"

    if line in sig_lines:
        return "signature"

    if "[[VAR:" in line or "<SPIN:" in line:
        pattern = "".join(r".+?" if part.startswith(("[[VAR:", "<SPIN:")) else re.escape(part)
                          for part in re.split(r"(\[\[VAR:[^\]]*\]\]|<SPIN:\d+>)", line) if part)
        try:
            if any(re.fullmatch(pattern, s) for s in sig_lines):
                return "signature"
        except re.error:
            pass

    line = collapse_first(re.sub(r"(?:<SPIN:\d+>|\[\[VAR:[^\]]*\]\])", "", raw if raw is not None else line)).strip(" ,.")

    if URL_ONLY_LINE_RE.match(line):
        return "url"
    if SENDER_TOKEN_RE.match(line):
        return "sender_token"
    if GREETING_RE.search(line):
        return "greeting"
    if SIGNOFF_RE.search(line):
        return "signoff"
    if UNSUB_RE.search(line):
        return "unsubscribe"
    return "body"


def fingerprint(data):
    """Fingerprint templates plus the cohort's rendered field values, deterministically"""
    canonical = []
    for seq in data["sequences"]:
        leads = []
        for lead in seq["leads"]:
            leads.append({"fields": lead.get("custom_fields") or {}, "body": lead.get("body") or lead.get("rendered_body") or ""})
        canonical.append({"id": str(seq.get("id") or seq.get("sequence_id") or seq.get("name") or "sequence"),
                          "template": seq.get("template") or seq.get("body_template") or "", "leads": leads})
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def sequence_templates(data):
    """[[template of each variant], ...] one list per sequence, in order, from normalised data."""
    out = []
    for seq in data["sequences"]:
        variants = [v.get("template") or "" for v in seq.get("variant_templates") or []]
        out.append(variants or [seq.get("template") or seq.get("body_template") or ""])
    return out


def live_sequence_templates(raw_sequences):
    """The same shape, straight from the platform's sequences response."""
    return [[s["template"] or "" for s in expand_variants(seq)] for seq in (raw_sequences or [])]


def template_fingerprint(templates):
    """Fingerprint of the copy as written (every variant of every step, in order), with no lead
    data. The receipt records it; the push wrapper recomputes it from the live sequences, so a
    receipt for copy that was edited afterwards stops matching."""
    canonical = [sorted(t.strip() for t in variants) for variants in templates]
    payload = json.dumps(canonical, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def normalise_rendered(raw, campaign_override=None):
    sequences = raw.get("sequences") if isinstance(raw, dict) else raw
    if not isinstance(sequences, list):
        raise ValueError("rendered input must contain a sequences array")
    result = {"campaign": str(campaign_override or (raw.get("campaign") if isinstance(raw, dict) else "") or "rendered"),
              "signature": (raw.get("signature") if isinstance(raw, dict) else "") or "",

              "signatures_all": (raw.get("signatures_all") if isinstance(raw, dict) else "") or "",
              "copy_fields": (raw.get("copy_fields") if isinstance(raw, dict) else None) or [],
              "sequences": []}

    signature = result["signature"]
    for pos, seq in enumerate(sequences, 1):
        leads = seq.get("leads") or []
        if not isinstance(leads, list):
            raise ValueError("sequence %s has no leads array" % pos)
        result["sequences"].append({"id": str(seq.get("id") or seq.get("sequence_id") or seq.get("name") or pos),
                                    "template": seq.get("template") or seq.get("body_template") or "",

                                    "leads": [_rendered_lead(lead, seq, signature) for lead in leads]})
    return result


def _rendered_lead(lead, seq, signature):
    fields = lead.get("custom_fields") or lead.get("fields") or {}
    template = lead.get("template") or ""
    body = lead.get("body") or lead.get("rendered_body") or ""
    if not body and signature:
        tpl = template or seq.get("template") or seq.get("body_template") or ""
        if tpl:
            body = substitute(tpl, fields).replace("%signature%", signature)
    return {"custom_fields": fields, "weight": float(lead.get("weight", 1.0)),
            "variant": lead.get("variant") or "A", "template": template, "body": body}


def expand_variants(seq):
    """One weighted entry per A/B variant of a Smartlead sequence"""
    variants = seq.get("sequence_variants") or seq.get("seq_variants") or []
    shaped = []
    for var in variants:

        # A variant deleted on the platform is still returned by the API but never sent.
        if var.get("is_deleted"):
            continue
        tpl = var.get("email_body") or var.get("seq_body") or ""
        try:
            pct = float(var.get("variant_distribution_percentage") or 0)
        except (TypeError, ValueError):
            pct = 0.0
        shaped.append({"template": tpl, "pct": pct, "label": var.get("variant_label") or "?"})
    if not shaped:
        shaped = [{"template": seq.get("email_body") or "", "pct": 100.0, "label": "A"}]

    total_pct = sum(s["pct"] for s in shaped)
    for s in shaped:
        s["weight"] = (s["pct"] / total_pct) if total_pct > 0 else (1.0 / len(shaped))
    return shaped


def get_live(campaign):
    key = os.environ.get("SMARTLEAD_API_KEY")
    if not key:
        sys.exit("Set SMARTLEAD_API_KEY to read a live campaign, or use --rendered.")
    base = "https://server.smartlead.ai/api/v1/campaigns/%s" % campaign
    def get(path):
        req = urllib.request.Request(base + path + ("&" if "?" in path else "?") + "api_key=" + key,
                                     headers={"User-Agent": "copy-variation-check/1"})
        try:
            return json.loads(urllib.request.urlopen(req, timeout=60).read())
        except Exception as exc:
            # Never print the URL: it carries the API key.
            sys.exit("Could not read campaign %s%s from the sending platform: %s. No PASS written."
                     % (campaign, path.split("?")[0], type(exc).__name__))
    sequences = get("/sequences") or []
    leads, offset = [], 0
    while True:
        page = get("/leads?offset=%d&limit=100" % offset)
        rows = page.get("data") or page.get("leads") or [] if isinstance(page, dict) else (page or [])
        leads.extend(rows)
        if len(rows) < 100:
            break
        offset += 100

    accounts = get("/email-accounts") or []

    signature = (accounts[0].get("signature") or "") if accounts else ""
    signatures_all = "\n".join((a.get("signature") or "") for a in accounts)
    result = {"campaign": str(campaign), "signature": signature,
              "signatures_all": signatures_all, "sequences": []}
    for pos, seq in enumerate(sequences, 1):

        shaped = expand_variants(seq)
        template = shaped[0]["template"]
        result["sequences"].append({
            "id": str(seq.get("id") or pos), "template": template or "",
            "variants": [{"label": s["label"], "weight": round(s["weight"], 4)} for s in shaped],
            "variant_templates": [{"label": s["label"], "weight": s["weight"], "template": s["template"] or ""} for s in shaped],
            "leads": []})
        for lead in leads:

            inner = lead.get("lead") if isinstance(lead.get("lead"), dict) else lead
            fields = inner.get("custom_fields") or {}

            for s in shaped:
                result["sequences"][-1]["leads"].append({
                    "custom_fields": fields,
                    "template": s["template"],
                    "weight": s["weight"],
                    "variant": s["label"],
                    "body": substitute(s["template"] or "", fields).replace("%signature%", signature)})
    return result


# Closing block: up to two short name/brand lines straight after the LAST sign-off line. Defined
# by shape, not by a brand string: few words, no sentence punctuation, never a P.S.
CLOSING_MAX_BLOCK_LINES = 2
CLOSING_MAX_WORDS = 4
CLOSING_SENTENCE_PUNCT_RE = re.compile(r"[.?!:;]")
CLOSING_CONNECTORS = {"de", "del", "la", "las", "los", "el", "y", "e", "&", "of", "the", "and", "for", "da", "do", "van", "von"}
CLOSING_PS_RE = re.compile(r"^\s*p\.?\s?[sd]\.?(\s|$|:)", re.I)


def is_closing_block_line(text):
    """Bare sender token, or a short name/brand line: <= CLOSING_MAX_WORDS words, no sentence"""
    txt = (text or "").strip()
    if not txt:
        return False
    if SENDER_TOKEN_RE.match(txt.strip(" ,.")):
        return True
    words = txt.split()
    if len(words) > CLOSING_MAX_WORDS or CLOSING_SENTENCE_PUNCT_RE.search(txt) or CLOSING_PS_RE.match(txt):
        return False
    return all(w[0].isupper() or w[0].isdigit() or w.lower() in CLOSING_CONNECTORS for w in words)


def evaluate_sequence(seq, allowlist, sig_lines=(), copy_fields=()):
    leads = seq["leads"]

    n = sum(float(x.get("weight", 1.0)) for x in leads)

    if n == 0:
        return {"id": seq.get("id"), "cohort_size": 0, "not_applicable": True,
                "reason": "no leads pushed yet - this gate measures rendered per-lead copy, "
                          "so it must run AFTER the push",
                "max_line_share": 0.0, "fixed_body_lines": [], "distinct_body_share": 1.0,
                "distinct_body_share_observed": None, "distinct_body_share_analytic_template": None,
                "exclusions": [], "body_shapes": {}}
    exclusions, line_counts, body_shapes = [], {}, {}
    masked_bodies = []
    for lead in leads:
        fields = lead["custom_fields"]
        w = float(lead.get("weight", 1.0))
        tpl = lead.get("template") or seq["template"]
        rendered = lead["body"] or substitute(tpl, fields)
        masked = plain(mask_values(rendered, fields, copy_fields)).strip()
        masked_bodies.append(masked)
        plain_lines = [x.strip() for x in plain(rendered).split("\n") if x.strip()]
        template_masked = plain(mask_values(substitute(tpl, fields), fields, copy_fields)).strip() if tpl else masked
        shape, states = spin_shape(template_masked)
        body_shapes[shape] = body_shapes.get(shape, {"count": 0, "states": states})
        body_shapes[shape]["count"] += w

        plan = mask_plan(rendered, fields, copy_fields)

        kinds = []
        for unmasked in plain_lines:
            ln, _st = spin_shape(mask_line(unmasked, plan))
            kinds.append(content_class(ln, allowlist, sig_lines, raw=unmasked))
        last_signoff = max((i for i, k in enumerate(kinds) if k == "signoff"), default=None)
        closing_idx = set()
        if last_signoff is not None:
            for j in range(last_signoff + 1, min(len(plain_lines), last_signoff + 1 + CLOSING_MAX_BLOCK_LINES)):
                if kinds[j] != "body":
                    continue
                if is_closing_block_line(plain_lines[j]):
                    closing_idx.add(j)
                else:
                    break
        for idx, unmasked in enumerate(plain_lines):
            raw_line = mask_line(unmasked, plan)

            line, states = spin_shape(raw_line)
            kind = kinds[idx]
            if idx in closing_idx:
                kind = "closing_block"
            if kind != "body":
                exclusions.append({"class": kind, "line": line})
                continue
            entry = line_counts.setdefault(line, {"count": 0.0, "states": states})
            entry["count"] += w
            entry["states"] = max(entry["states"], states)

    observed_distinct = min(1.0, len(set(masked_bodies)) / n) if n else 0

    expected_distinct = 0.0
    for item in body_shapes.values():
        count, states = item["count"], max(1, item["states"])
        expected_distinct += min(count, states * (1 - (1 - 1 / states) ** count))
    analytic_distinct = expected_distinct / n if n else 0

    observed_distinct_count = len(set(masked_bodies))
    template_states = max(1, max((item["states"] for item in body_shapes.values()), default=1))
    combined = min(n, observed_distinct_count * template_states) if n else 0
    distinct_share = (combined / n) if n else 0

    scored = [(line, v["count"], v["states"], v["count"] / n / max(1, v["states"]) if n else 0.0)
              for line, v in line_counts.items()]
    worst = sorted(scored, key=lambda x: (-x[3], x[0]))[:10]
    max_share = worst[0][3] if worst else 0.0

    fixed = [line for line, count, states, share in scored if count >= n - 1e-6 and states == 1]
    return {"id": seq["id"], "cohort_size": n, "max_line_share": max_share,
            "fixed_body_lines": fixed, "distinct_body_share": distinct_share,
            "distinct_body_share_observed": observed_distinct,
            "distinct_body_share_analytic_template": analytic_distinct,
            "template_spintax_states": template_states,
            "measurement": "observed_field_variation x analytic_template_spintax_states",
            "worst_offending_lines": [{"line": line, "count": count, "branches": states, "effective_share": share}
                                      for line, count, states, share in worst],
            "exclusions_applied": exclusions}


def apply_exclusions(spec):
    """Replace the default greeting / sign-off / unsubscribe patterns (Spanish and English)
    with your own. Keys you leave out keep their defaults."""
    global GREETING_RE, SIGNOFF_RE, UNSUB_RE
    text = spec.strip()
    if not text.startswith("{"):
        with open(text, encoding="utf-8") as fh:
            text = fh.read()
    overrides = json.loads(text)
    unknown = set(overrides) - {"greeting", "signoff", "unsubscribe"}
    if unknown:
        sys.exit("--exclusions: unknown key(s) %s; use greeting, signoff, unsubscribe" % ", ".join(sorted(unknown)))
    if "greeting" in overrides:
        GREETING_RE = re.compile(overrides["greeting"], re.I)
    if "signoff" in overrides:
        SIGNOFF_RE = re.compile(overrides["signoff"], re.I)
    if "unsubscribe" in overrides:
        UNSUB_RE = re.compile(overrides["unsubscribe"], re.I)


def _self_test():
    """RED/GREEN fixtures for the closing-block rule and the zero-lead accounting"""
    def seq(bodies, sid="s"):
        return {"id": sid, "template": "", "leads": [{"custom_fields": {}, "body": b, "weight": 1.0} for b in bodies]}
    def lines(*ls): return "".join("<div>%s</div>" % x for x in ls)
    n = 20

    varied = [lines("Hello Ann,", "I came across School%d and wanted to share idea number %d for your class." % (i, i),
                    "Best regards,", "%sender-name%", "Acme Travel") for i in range(n)]
    r = evaluate_sequence(seq(varied), set())
    assert r["fixed_body_lines"] == [] and r["max_line_share"] < 0.15, ("closing block must be exempt", r["fixed_body_lines"], r["max_line_share"])
    assert any(e["class"] == "closing_block" for e in r["exclusions_applied"])

    rep = [lines("Hello Ann,", "We create tailored programs in town for every Spanish class this year", "Best regards,", "Acme Travel") for i in range(n)]
    r = evaluate_sequence(seq(rep), set())
    assert r["fixed_body_lines"] and r["max_line_share"] > 0.15, r

    ps = [lines("Hello Ann,", "Unique line %d about your school and what we could do." % i, "Best regards,",
                "P.S. We also run a free teacher trip every spring.") for i in range(n)]
    r = evaluate_sequence(seq(ps), set())
    assert r["fixed_body_lines"], "post-signoff sentence must stay measured"

    pre = [lines("Acme Travel", "Unique line %d about your school and what we could do." % i, "Best regards,") for i in range(n)]
    r = evaluate_sequence(seq(pre), set())
    assert "Acme Travel" in r["fixed_body_lines"], r["fixed_body_lines"]

    for tail in ("Book a call with us here", "PS does Tuesday work for you"):
        sc = [lines("Hello Ann,", "Unique line %d about your school and what we could do for you." % i, "Thanks", tail) for i in range(n)]
        r = evaluate_sequence(seq(sc), set())
        assert tail in r["fixed_body_lines"], (tail, r["fixed_body_lines"])

    op = [lines("Saludos,", "Te escribo por Colegio%d" % (i % 2), "Unique line %d about your school and what we could do." % i) for i in range(n)]
    r = evaluate_sequence(seq(op), set())
    assert not any(e["class"] == "closing_block" for e in r["exclusions_applied"]), r["exclusions_applied"]

    cb = [lines("Hello Ann,", "Unique line %d about your school and what we could do for you." % i, "{Best regards|Kind regards},", "%sender-name%", "Colegio de Ejemplo") for i in range(n)]
    r = evaluate_sequence(seq(cb), set())
    assert r["fixed_body_lines"] == [], r["fixed_body_lines"]

    r = evaluate_sequence(seq([]), set())
    assert r.get("not_applicable") is True
    c = result_counts([r]); assert c == {"attempted": 1, "evaluated": 0, "passed": 0, "failed": 0, "skipped": 1}, c

    sh = expand_variants({"sequence_variants": [{"email_body": "a", "variant_label": "A"},
                                                {"email_body": "b", "variant_label": "B"},
                                                {"email_body": "<div>deleted</div>", "variant_label": "C", "is_deleted": True}]})
    assert [s["label"] for s in sh] == ["A", "B"] and abs(sh[0]["weight"] - 0.5) < 1e-9, sh
    print("SELF-TEST PASS: check-copy-variation closing block + zero-lead accounting (RED + GREEN)")


def result_counts(results, failures=()):
    """attempted/evaluated/passed/failed/skipped over sequences. skipped = unmeasured (0 leads)"""
    failed_ids = {str(f[0]) for f in failures}
    evaluated = [r for r in results if not r.get("not_applicable")]
    failed = sum(1 for r in evaluated if str(r["id"]) in failed_ids)
    return {"attempted": len(results), "evaluated": len(evaluated), "passed": len(evaluated) - failed,
            "failed": failed, "skipped": len(results) - len(evaluated)}


def main():
    if "--self-test" in sys.argv:
        _self_test(); return
    parser = argparse.ArgumentParser()
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--campaign")
    source.add_argument("--rendered")
    parser.add_argument("--client", default="campaign", help="label used in the report filename")

    parser.add_argument("--top-up", metavar="RENDERED_JSON",
                        help="rendered JSON of the new batch; measured as a union with the live cohort")
    parser.add_argument("--small-cohort-ack")
    parser.add_argument("--allow-fixed-line", action="append", default=[])
    parser.add_argument("--fingerprint-only", action="store_true")
    parser.add_argument("--template-fingerprint-only", action="store_true",
                        help="print the fingerprint of the sequence templates alone (what the push wrapper recomputes live)")
    parser.add_argument("--leads-file",
                        help="the exact leads file that will be pushed; its sha256 goes into the receipt so the "
                             "push wrapper can refuse a receipt made for a different file")

    parser.add_argument("--copy-field", action="append", default=[],
                        help="custom field that carries copy rather than lead data; measured, not masked")
    parser.add_argument("--out-dir", default=".", help="where the PASS/FAIL report JSON is written")
    parser.add_argument("--exclusions", metavar="JSON",
                        help='override the excluded-line regexes for your language: a JSON file, or an inline '
                             'object, with any of "greeting", "signoff", "unsubscribe" (case-insensitive regex strings)')
    args = parser.parse_args()
    if args.exclusions:
        apply_exclusions(args.exclusions)
    if args.rendered:
        data = normalise_rendered(json.load(open(args.rendered)), args.campaign)
    else:
        data = get_live(args.campaign)
    if isinstance(args.top_up, str):
        raw_top = json.load(open(args.top_up))

        if isinstance(raw_top, list) and raw_top and isinstance(raw_top[0], dict) \
                and "leads" not in raw_top[0] and "sequences" not in raw_top[0]:
            if not data["sequences"]:
                raise ValueError("flat-row --top-up needs a live campaign with sequences")
            sig = data.get("signature") or ""

            raw_top = [r["custom_fields"] if isinstance(r.get("custom_fields"), dict) else r for r in raw_top]
            raw_top = {"sequences": [
                {"id": seq["id"], "template": seq["template"],
                 "leads": [{"custom_fields": row, "template": seq["template"],
                            "body": substitute(seq["template"], row).replace("%signature%", sig)}
                           for row in raw_top]}
                for seq in data["sequences"]]}
        top = normalise_rendered(raw_top, data["campaign"])
        by_id = {seq["id"]: seq for seq in data["sequences"]}
        for seq in top["sequences"]:
            if seq["id"] in by_id:
                by_id[seq["id"]]["leads"].extend(seq["leads"])
            else:
                by_id[seq["id"]] = seq
        data["sequences"] = list(by_id.values())
    if not data["sequences"]:
        # Nothing was measured, so nothing can pass. A campaign with no sequences sends nothing.
        print("REFUSED copy variation for campaign %s: zero sequences, nothing was measured. No PASS artifact written."
              % data["campaign"], file=sys.stderr)
        sys.exit(2)
    fp = fingerprint(data)
    template_fp = template_fingerprint(sequence_templates(data))
    if args.fingerprint_only:
        print(fp); return
    if args.template_fingerprint_only:
        print(template_fp); return
    leads_sha = None
    if args.leads_file:
        with open(args.leads_file, "rb") as fh:
            leads_sha = hashlib.sha256(fh.read()).hexdigest()

    template_only = set()
    for seq in data["sequences"]:
        vts = seq.get("variant_templates") or ([{"label": "A", "weight": 1.0, "template": seq.get("template") or ""}] if seq.get("template") else [])
        if not seq["leads"] and vts and any(v["template"].strip() for v in vts):
            sig = data.get("signature") or ""
            seq["leads"] = [{"custom_fields": {}, "template": v["template"], "weight": v["weight"], "variant": v["label"],
                             "body": substitute(v["template"], {}).replace("%signature%", sig)} for v in vts if v["template"].strip()]
            template_only.add(str(seq["id"]))

    sig_lines = {spin_shape(x.strip())[0]
                 for x in plain(data.get("signatures_all") or data.get("signature") or "").split("\n")
                 if x.strip()}
    copy_fields = list(data.get("copy_fields") or []) + [f for f in args.copy_field if f not in (data.get("copy_fields") or [])]
    data["copy_fields"] = copy_fields
    if copy_fields:
        seen = {}
        for seq in data["sequences"]:
            for lead in seq["leads"]:
                for key in copy_fields:
                    v = (lead.get("custom_fields") or {}).get(key)
                    if v is not None:
                        seen.setdefault(key, set()).add(str(v))
        bad = {k: len(v) for k, v in seen.items() if len(v) > COPY_FIELD_MAX_DISTINCT}
        missing = [k for k in copy_fields if k not in seen]
        if bad or missing:
            parser.error(
                "copy_fields declaration refused: %s. A copy field is drawn from a small approved "
                "set; more than %d distinct values across the cohort means it is lead DATA and "
                "must stay masked." % (
                    "; ".join(["%s has %d distinct values" % (k, n) for k, n in sorted(bad.items())]
                              + ["%s appears on no lead" % k for k in missing]),
                    COPY_FIELD_MAX_DISTINCT))
        print("copy_fields measured, not masked: " + ", ".join(
            "%s (%d renderings)" % (k, len(seen[k])) for k in copy_fields))
    results = [evaluate_sequence(seq, set(args.allow_fixed_line), sig_lines, copy_fields)
               for seq in data["sequences"]]
    failures = []
    for result in results:

        if result.get("not_applicable"):
            continue
        if str(result["id"]) in template_only:
            result["mode"] = "template_only"
            if result["max_line_share"] > MAX_LINE_SHARE:
                failures.append((result["id"], "max_line_share", "%.1f%% > 15%%" % (result["max_line_share"] * 100)))
            if result["fixed_body_lines"]:
                failures.append((result["id"], "fixed_body_lines", "; ".join(result["fixed_body_lines"][:3])))
            continue
        if result["cohort_size"] < MIN_COHORT and not args.small_cohort_ack:
            failures.append((result["id"], "small_cohort", "requires --small-cohort-ack"))
        if result["max_line_share"] > MAX_LINE_SHARE:
            failures.append((result["id"], "max_line_share", "%.1f%% > 15%%" % (result["max_line_share"] * 100)))
        if result["fixed_body_lines"]:
            failures.append((result["id"], "fixed_body_lines", "; ".join(result["fixed_body_lines"][:3])))
        if result["distinct_body_share"] < MIN_DISTINCT_SHARE:
            failures.append((result["id"], "distinct_body_share", "%.1f%% < 90%%" % (result["distinct_body_share"] * 100)))
    counts = result_counts(results, failures)
    print("sequences: attempted=%(attempted)d evaluated=%(evaluated)d passed=%(passed)d failed=%(failed)d skipped=%(skipped)d" % counts,
          file=sys.stderr if failures else sys.stdout)
    mode = "template_only" if template_only and len(template_only) == len(results) else \
           ("mixed" if template_only else "rendered")
    report = {"passed": not failures, "mode": mode, "client": args.client, "campaign": data["campaign"], "fingerprint": fp,
              "template_fingerprint": template_fp, "leads_sha256": leads_sha,
              "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "top_up_union": bool(args.top_up),
              "thresholds": {"max_line_share": MAX_LINE_SHARE, "fixed_body_lines": 0, "distinct_body_share": MIN_DISTINCT_SHARE},
              "simulation_caveat": "Template spintax shares are expected values under uniform Smartlead branch selection, not observed sends.",
              "copy_fields_declared": copy_fields, "counts": counts,
              "sequences": results, "pooled_info_only": {"sequences": len(results), "leads": sum(r["cohort_size"] for r in results)},
              "failures": [{"sequence": x[0], "metric": x[1], "detail": x[2]} for x in failures]}
    safe_client = re.sub(r"[^A-Za-z0-9_-]", "_", args.client)
    safe_campaign = re.sub(r"[^A-Za-z0-9_-]", "_", data["campaign"])
    path = os.path.join(args.out_dir, "copy-variation-PASS-%s-%s.json" % (safe_client, safe_campaign))

    if results and all(r.get("not_applicable") for r in results):
        print("NOT APPLICABLE copy variation for campaign %s: every sequence has 0 leads." % data["campaign"])
        print("  This gate measures RENDERED per-lead copy. It gives no signal before the push and")
        print("  must be re-run once leads are loaded. No PASS artifact written.")
        sys.exit(3)
    if not failures:
        with open(path, "w") as f: json.dump(report, f, ensure_ascii=False, indent=2); f.write("\n")
        print("PASS copy variation: %s" % path)
        return

    fail_path = os.path.join(args.out_dir, "copy-variation-FAIL-%s-%s.json" % (safe_client, safe_campaign))
    with open(fail_path, "w") as f: json.dump(report, f, ensure_ascii=False, indent=2); f.write("\n")
    print("FAIL copy variation for campaign %s" % data["campaign"], file=sys.stderr)
    by_id = {r["id"]: r for r in results}
    for seq, metric, detail in failures:
        print("  sequence %s: %s - %s" % (seq, metric, detail), file=sys.stderr)
        if metric == "max_line_share":
            for w in (by_id.get(seq, {}).get("worst_offending_lines") or [])[:3]:
                print("      %5.1f%% (%s on %.0f leads, %d branch(es)): %s"
                      % (w["effective_share"] * 100, "seen", w["count"], w["branches"], w["line"][:160]),
                      file=sys.stderr)
    print("  report: %s" % fail_path, file=sys.stderr)
    print("Review deliberate short bump/breakup emails and client-mandated fixed lines; allowlist only genuine mandated lines.", file=sys.stderr)
    sys.exit(1)

if __name__ == "__main__":
    main()
