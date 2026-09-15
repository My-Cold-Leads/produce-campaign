#!/usr/bin/env python3
"""Check that no sentence repeats across too many of your outgoing cold emails.

Measures the FINAL emails (custom fields filled in, spintax expanded) and fails when:
  - any body line reaches more than 15% of recipients (after spintax branching), or
  - any body line is identical for the whole cohort (a fixed line), or
  - fewer than 90% of the emails are distinct from each other.
Greetings, sign-offs, signatures, unsubscribe lines and URL-only lines are excluded.

Inputs:
  --rendered file.json   a JSON file with your templates and per-lead fields (works before you send)
  --campaign ID          read a live Smartlead campaign (needs SMARTLEAD_API_KEY in the environment)

Template spintax shares are expected values under uniform branch selection, not observed sends.
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
GREETING_RE = re.compile(
    r"^(hola|buenas|buenos días|buenas tardes|buenas noches|qué tal|que tal|hello|hi|hey)"
    r"\b[^.!?¿¡,]{0,30}$", re.I)
SIGNOFF_RE = re.compile(
    r"^(un saludo|saludos|un abrazo|un fuerte abrazo|un cordial saludo|gracias|best|"
    r"kind regards|atentamente|"
    r"espero que (sirva|os sirva|te sirva|ayude|os ayude)|"
    r"que (te vaya bien|vaya todo bien)|[a-záéíóúñ]+,)$", re.I)
UNSUB_RE = re.compile(r"(unsubscribe|cancelar suscripción|darse de baja|dar(?:se|te|os)? de baja|no recibir|dejar de recibir|responder .?baja)", re.I)
URL_ONLY_LINE_RE = re.compile(r"^https?://\S+$", re.I)
VAR_RE = re.compile(r"\{\{\s*([^} ]+)\s*\}\}")


def plain(value):
    value = html.unescape(value or "")
    value = re.sub(r"<(?:br|/div|/p|/li)\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    return value.replace("\r\n", "\n").replace("\r", "\n")


MERGE_TOKEN_MAX_SHARE = 0.25


OWN_LINE_RE_CACHE = {}


def occupies_own_line(text, value):
    """True when `value` sits alone as a whole line of the body (so it is copy, not a merge token)."""
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


def mask_values(text, fields):
    """Mask short per-lead merge tokens (name, company, city) before measuring.
    
    Without masking, a plain mail-merge looks 100% distinct while a spam filter sees one template.
    Values that are most of the body, or a whole line of their own, are copy and are measured instead.
    """
    body_len = max(1, len(text))
    values = [(str(k), str(v)) for k, v in (fields or {}).items() if str(v).strip()]
    for key, value in sorted(values, key=lambda item: len(item[1]), reverse=True):
        if len(value) / body_len >= MERGE_TOKEN_MAX_SHARE:
            continue
        if occupies_own_line(text, value):
            continue
        if len(value) < 3:
            continue
        text = re.sub(re.escape(value), "[[VAR:%s]]" % key, text, flags=re.I)
    return text


def substitute(template, fields):
    return VAR_RE.sub(lambda m: str((fields or {}).get(m.group(1), m.group(0))), template or "")


def spin_shape(text):
    """Return a spintax shape and its number of uniform states."""
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
    """Collapse each spintax block to its first branch, for classifying a line only."""
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
    if GREETING_RE.search(line):
        return "greeting"
    if SIGNOFF_RE.search(line):
        return "signoff"
    if UNSUB_RE.search(line):
        return "unsubscribe"
    return "body"


def fingerprint(data):
    """Fingerprint templates plus the cohort's rendered field values, deterministically."""
    canonical = []
    for seq in data["sequences"]:
        leads = []
        for lead in seq["leads"]:
            leads.append({"fields": lead.get("custom_fields") or {}, "body": lead.get("body") or lead.get("rendered_body") or ""})
        canonical.append({"id": str(seq.get("id") or seq.get("sequence_id") or seq.get("name") or "sequence"),
                          "template": seq.get("template") or seq.get("body_template") or "", "leads": leads})
    payload = json.dumps(canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode()).hexdigest()


def normalise_rendered(raw, campaign_override=None):
    sequences = raw.get("sequences") if isinstance(raw, dict) else raw
    if not isinstance(sequences, list):
        raise ValueError("rendered input must contain a sequences array")
    result = {"campaign": str(campaign_override or (raw.get("campaign") if isinstance(raw, dict) else "") or "rendered"),
              "signature": (raw.get("signature") if isinstance(raw, dict) else "") or "", "sequences": []}
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
    """One weighted entry per A/B variant of a Smartlead sequence.
    
    A line living in one variant only reaches that variant's share of recipients.
    """
    variants = seq.get("sequence_variants") or seq.get("seq_variants") or []
    shaped = []
    for var in variants:
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
        return json.loads(urllib.request.urlopen(req, timeout=60).read())
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


def evaluate_sequence(seq, allowlist, sig_lines=()):
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
        masked = plain(mask_values(rendered, fields)).strip()
        masked_bodies.append(masked)
        plain_lines = [x.strip() for x in plain(rendered).split("\n") if x.strip()]
        template_masked = plain(mask_values(substitute(tpl, fields), fields)).strip() if tpl else masked
        shape, states = spin_shape(template_masked)
        body_shapes[shape] = body_shapes.get(shape, {"count": 0, "states": states})
        body_shapes[shape]["count"] += w
        masked_lines = [x.strip() for x in masked.split("\n") if x.strip()]
        for idx, raw_line in enumerate(masked_lines):
            unmasked = plain_lines[idx] if idx < len(plain_lines) else raw_line
            line, states = spin_shape(raw_line)
            kind = content_class(line, allowlist, sig_lines, raw=unmasked)
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


def main():
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
        top = normalise_rendered(json.load(open(args.top_up)), data["campaign"])
        by_id = {seq["id"]: seq for seq in data["sequences"]}
        for seq in top["sequences"]:
            if seq["id"] in by_id:
                by_id[seq["id"]]["leads"].extend(seq["leads"])
            else:
                by_id[seq["id"]] = seq
        data["sequences"] = list(by_id.values())
    fp = fingerprint(data)
    if args.fingerprint_only:
        print(fp); return
    sig_lines = {spin_shape(x.strip())[0]
                 for x in plain(data.get("signatures_all") or data.get("signature") or "").split("\n")
                 if x.strip()}
    results = [evaluate_sequence(seq, set(args.allow_fixed_line), sig_lines) for seq in data["sequences"]]
    failures = []
    for result in results:
        if result.get("not_applicable"):
            continue
        if result["cohort_size"] < MIN_COHORT and not args.small_cohort_ack:
            failures.append((result["id"], "small_cohort", "requires --small-cohort-ack"))
        if result["max_line_share"] > MAX_LINE_SHARE:
            failures.append((result["id"], "max_line_share", "%.1f%% > 15%%" % (result["max_line_share"] * 100)))
        if result["fixed_body_lines"]:
            failures.append((result["id"], "fixed_body_lines", "; ".join(result["fixed_body_lines"][:3])))
        if result["distinct_body_share"] < MIN_DISTINCT_SHARE:
            failures.append((result["id"], "distinct_body_share", "%.1f%% < 90%%" % (result["distinct_body_share"] * 100)))
    report = {"passed": not failures, "client": args.client, "campaign": data["campaign"], "fingerprint": fp,
              "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(), "top_up_union": bool(args.top_up),
              "thresholds": {"max_line_share": MAX_LINE_SHARE, "fixed_body_lines": 0, "distinct_body_share": MIN_DISTINCT_SHARE},
              "simulation_caveat": "Template spintax shares are expected values under uniform Smartlead branch selection, not observed sends.",
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
