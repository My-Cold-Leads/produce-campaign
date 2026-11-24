#!/usr/bin/env python3
"""Run Approval Bundle: ask for every approval a campaign run needs ONCE, save the answer, and
let the gates read it instead of asking again.

The human touchpoints of a run (4 to 6, never one per step):
  1. The up-front bundle (propose): scope, cohort size, a spend cap per provider, the step skips
     that are allowed and the condition for each, the contact search plan, who writes the copy,
     the false-positive bypass policy, "an unsure lead is paused, never sent", and "no per-step
     confirmations".
  2. Offer + 10 examples (propose-offer), only when the offer or the prompt is new or changed.
  3. Final copy sign-off plus the DRAFT push of the named campaigns, in one reply (propose-signoff).
  4. Go-live (propose-go-live), one campaign per ask.
  5. One exceptions digest (digest-add / digest-show), only if something tripped.

A yes in any wording counts ("yes", "all good", "go ahead", "vale", "de acuerdo"). No magic phrase.

What the code holds, whatever the wording of the reply:
  - A record belongs to ONE run (--run). A decision for another run is never found.
  - Every decision expires. An expired decision is the same as no decision.
  - A declined item is saved as declined and never counts. An item whose terms changed in the
    reply (a different money figure) stays open and is asked again.
  - A spend approval is bound to its provider. The cap is cumulative for the run.
  - The bundle can never carry a push, a go-live, a send, a deletion or a suppression change.
  - A logged false-positive bypass needs the bundle's policy, a gate on the allowed list, and a
    quote that names that gate and was said AFTER the bundle was recorded.
  - The copy sign-off is read only by the push wrapper, as its approval gate. It never releases a
    raw HTTP push or a direct MCP push. It covers a push only into the campaign ids it names, of
    the sending account it names, of the exact leads file it hashed, only while the campaign is
    DRAFTED or PAUSED, only while the live copy fingerprint is the one that was signed, and never
    a start. Go-live is always its own ask.

What it cannot prove: that a human typed the reply. It stores the words it was given, with the
time. Keep the reply step with a person: paste their message, do not write it for them.

Python 3 standard library only. The record is one JSON file per run in CAMPAIGN_STATE_DIR
(default .claude/campaign-state).

    python3 scripts/run-approvals.py propose --run acme-q1 --client ACME --plan plan.json
    python3 scripts/run-approvals.py record  --run acme-q1 --reply "yes, all good"
    python3 scripts/run-approvals.py check   --run acme-q1 --kind spend --key enrichment --amount 12
    python3 scripts/run-approvals.py status  --run acme-q1
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import sys

BUNDLE_DEFAULT_TTL_HOURS = 72
BUNDLE_MAX_TTL_HOURS = 168
SIGNOFF_DEFAULT_TTL_HOURS = 24
SIGNOFF_MAX_TTL_HOURS = 72
GO_LIVE_TTL_HOURS = 24
OFFER_EXAMPLES = 10
DRAFT_STATUSES = ("DRAFTED", "PAUSED")

BUNDLE_KINDS = ("run_setting", "spend", "skip_step", "contact_search", "false_positive_bypass", "hold_policy")
SEPARATE_KINDS = ("offer_signoff", "copy_signoff_draft_push", "go_live")
BUNDLE_REQUIRED = ("run_setting:scope", "run_setting:cohort_target", "run_setting:copy_author",
                   "run_setting:no_step_confirmations", "contact_search:plan",
                   "false_positive_bypass:policy", "hold_policy:unsure_lead_pause")

# A false-positive bypass may never be recorded for a gate that protects recipients or sending.
BYPASS_NEVER = re.compile(r"harden|suppress|do.?not.?contact|dnc|unsubscrib|block.?list|push|send|start|launch|go.?live|activat", re.I)
# Nothing shaped like these may ride inside the up-front bundle.
EXCLUDED_IN_BUNDLE = re.compile(
    r"\b(push\w*|upload\w*|go.?live|launch\w*|activat\w*|start\w*|resum\w*|send\w*|delet\w*|drop\w*|"
    r"purg\w*|wipe\w*|unsuppress\w*|ad.?spend|ads? budget)\b", re.I)
# The sign-off label may not describe a start or a settings change.
SIGNOFF_LABEL_NEVER = re.compile(r"\b(start\w*|activat\w*|launch\w*|go.?live|resum\w*|enabl\w*|schedul\w*|settings?)\b", re.I)

AFFIRM = re.compile(
    r"\b(yes|yep|yeah|yup|ok|okay|approved?|agreed?|go ahead|go for it|fine|sure|all good|sounds good|"
    r"perfect|great|correct|exactly|do it|do that|that works|works for me|confirmed?|proceed|"
    r"s[ií]|vale|perfecto|claro|de acuerdo|adelante|todo bien|hazlo|conforme)\b", re.I)
NO_PROBLEM = re.compile(r"^\W*no (problem|worries|issues?|objections?|hay problema)\b", re.I)
OPENS_NEGATIVE = re.compile(
    r"^\W*(no|nope|not|don'?t|do not|never|stop|cancel|reject\w*|declin\w*|hold|wait|nunca|para|espera|rechaz\w*)\b", re.I)
EXCEPT = re.compile(r"\b(except|but not|apart from|excluding|other than|excepto|menos|salvo)\b([^.\n]*)", re.I)
NUMBERED = re.compile(r"^\s*(?:item\s*)?#?(\d{1,2})\s*[).:=-]?\s+(.*)$", re.I)
MONEY = re.compile(r"(?:[$€£]\s?(\d+(?:[.,]\d+)?))|(?:(\d+(?:[.,]\d+)?)\s?(?:usd|eur|gbp|dollars?|euros?|pounds?)\b)", re.I)
RUN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,79}$")


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def parse_time(value):
    when = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return when if when.tzinfo else when.replace(tzinfo=dt.timezone.utc)


def state_dir():
    return os.environ.get("CAMPAIGN_STATE_DIR") or os.path.join(".claude", "campaign-state")


def record_path(run, base=None):
    if not RUN_RE.match(str(run or "")):
        raise ValueError("run key must be letters, digits, dot, dash or underscore (got %r)" % (run,))
    return os.path.join(base or state_dir(), "run-approvals-%s.json" % run)


def load_record(run, base=None):
    """The record for this run, or an empty one. An unreadable file raises: unknown is not approved."""
    path = record_path(run, base)
    if not os.path.exists(path):
        return {"run": str(run), "client": "", "pending": None, "bundle": None, "decisions": [], "digest": []}
    with open(path, encoding="utf-8") as fh:
        doc = json.load(fh)
    if not isinstance(doc, dict) or str(doc.get("run")) != str(run):
        raise ValueError("the approvals file at %s is for run %r, not %r" % (path, doc.get("run") if isinstance(doc, dict) else None, run))
    for key, empty in (("decisions", []), ("digest", [])):
        if not isinstance(doc.get(key), list):
            doc[key] = empty
    return doc


def save_record(record, base=None):
    path = record_path(record["run"], base)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(record, fh, ensure_ascii=False, indent=1)
        fh.write("\n")
    os.replace(tmp, path)
    return path


def item_id(item):
    return "%s:%s" % (item.get("kind"), item.get("key"))


def excluded_reason(item):
    """Why this item can never sit in the up-front bundle, or None."""
    if item.get("kind") in SEPARATE_KINDS:
        return "%s is its own touchpoint and is never part of the up-front bundle" % item["kind"]
    if item.get("kind") not in BUNDLE_KINDS:
        return "unknown kind %r" % (item.get("kind"),)
    text = "%s %s" % (item.get("key") or "", item.get("label") or "")
    if item["kind"] == "false_positive_bypass" and item.get("key") != "policy" and BYPASS_NEVER.search(str(item.get("key"))):
        return "a false-positive bypass can never be approved for the gate %r" % item.get("key")
    if item["kind"] in ("run_setting", "skip_step", "contact_search", "spend") and EXCLUDED_IN_BUNDLE.search(text):
        return "pushes, go-live, sends, deletions and ad spend keep their own approval and cannot be bundled"
    return None


def build_bundle_items(plan):
    """Turn the operator's plan into the list of decisions. Raises ValueError naming what is missing."""
    def need(key, what):
        value = plan.get(key)
        if value in (None, "", [], {}):
            raise ValueError("the plan is missing %s (%s)" % (key, what))
        return value

    items = [
        {"kind": "run_setting", "key": "scope", "label": "scope of this run: %s" % need("scope", "segments, regions, roles")},
        {"kind": "run_setting", "key": "cohort_target", "label": "cohort size: %s leads" % need("cohort_target", "a number")},
        {"kind": "run_setting", "key": "copy_author", "label": "who writes the copy: %s" % need("copy_author", "a person, a model, or 'existing copy only'")},
        {"kind": "run_setting", "key": "no_step_confirmations",
         "label": "steps that need no decision run straight through; I stop only at the touchpoints listed at the end"},
    ]
    caps = plan.get("caps") or {}
    if not isinstance(caps, dict):
        raise ValueError("caps must be an object of provider -> USD cap")
    for provider, cap in sorted(caps.items()):
        try:
            cap = float(cap)
        except (TypeError, ValueError):
            raise ValueError("the cap for %r is not a number" % provider)
        if cap <= 0:
            raise ValueError("the cap for %r must be above zero; leave the provider out to spend nothing" % provider)
        items.append({"kind": "spend", "key": str(provider).strip().lower(), "cap_usd": cap,
                      "label": "%s: spend up to $%s on this run, hard cap" % (provider, ("%.2f" % cap).rstrip("0").rstrip("."))})
    for skip in plan.get("skips") or []:
        if not str(skip.get("condition") or "").strip():
            raise ValueError("skip of step %r has no condition; a skip is only ever allowed under a stated condition" % skip.get("step"))
        items.append({"kind": "skip_step", "key": str(skip.get("step")), "condition": str(skip["condition"]).strip(),
                      "label": "skip step %s (%s) only if: %s" % (skip.get("step"), skip.get("label") or "no label", str(skip["condition"]).strip())})
    search = need("contact_search", "the search plan, or {\"none\": true, \"reason\": ...}")
    if not isinstance(search, dict):
        raise ValueError("contact_search must be an object")
    if search.get("none"):
        if not str(search.get("reason") or "").strip():
            raise ValueError("contact_search none:true needs a reason")
        label = "no contact search on this run: %s" % search["reason"]
    else:
        for key in ("methods", "roles", "max_companies"):
            if search.get(key) in (None, "", []):
                raise ValueError("contact_search needs %s" % key)
        label = "contact search: %s, for %s, at up to %s companies" % (
            ", ".join(map(str, search["methods"])), ", ".join(map(str, search["roles"])), search["max_companies"])
    items.append({"kind": "contact_search", "key": "plan", "plan": search, "label": label})
    items.append({"kind": "false_positive_bypass", "key": "policy",
                  "label": "if a listed gate fires on something a second reviewer and a failing-then-passing fixture show "
                           "is a false positive, I may use that gate's logged bypass; never for suppression, hardening, pushes or sends"})
    for gate in plan.get("false_positive_gates") or []:
        items.append({"kind": "false_positive_bypass", "key": str(gate).strip().lower(),
                      "label": "false-positive bypass allowed for the gate: %s" % gate})
    items.append({"kind": "hold_policy", "key": "unsure_lead_pause",
                  "label": "a lead I am unsure about is paused and listed in the exceptions digest, never sent"})
    for item in items:
        why = excluded_reason(item)
        if why:
            raise ValueError("item %s cannot be in the bundle: %s" % (item_id(item), why))
    return items


def new_pending(kind, items, ttl_hours, now=None):
    now = now or now_utc()
    for n, item in enumerate(items, 1):
        item["n"] = n
    token = "RA-" + hashlib.sha256(json.dumps([kind, items, now.isoformat()], sort_keys=True).encode()).hexdigest()[:8]
    return {"token": token, "ask": kind, "proposed_at": now.isoformat(), "ttl_hours": ttl_hours, "items": items}


TOUCHPOINTS = (
    "After this I stop only for: (2) the offer and 10 examples, if either is new or changed; "
    "(3) the final copy sign-off and the DRAFT push of the named campaigns, in one reply; "
    "(4) go-live; (5) one exceptions digest, only if something trips.")


def ask_text(record):
    """The ONE message to show the human. Print it unchanged."""
    pending = record["pending"]
    head = {"bundle": "Run approvals for %s (%s). One reply covers the run; answer in any words, or per number.",
            "offer_signoff": "Offer and examples sign-off for %s (%s).",
            "copy_signoff_draft_push": "Final copy sign-off and DRAFT push for %s (%s). One reply covers both.",
            "go_live": "Go-live for %s (%s)."}[pending["ask"]] % (record["run"], record.get("client") or "no client set")
    lines = [head, ""]
    lines += ["%d. %s" % (item["n"], item["label"]) for item in pending["items"]]
    lines += ["", "Valid for %s hours. Ref %s." % (pending["ttl_hours"], pending["token"])]
    if pending["ask"] == "bundle":
        lines.append(TOUCHPOINTS)
    return "\n".join(lines)


def verdict_of(text):
    """'approved', 'declined' or 'open' for one piece of the reply. Wording is not the bar: any
    plain agreement counts. A reply that OPENS with a refusal is a refusal even if a yes follows."""
    text = (text or "").strip()
    if not text:
        return "open"
    if NO_PROBLEM.search(text):
        return "approved"
    if OPENS_NEGATIVE.search(text):
        return "declined"
    return "approved" if AFFIRM.search(text) else "open"


def money_figures(text):
    out = []
    for a, b in MONEY.findall(text or ""):
        try:
            out.append(float((a or b).replace(",", ".")))
        except ValueError:
            pass
    return out


def evaluate_reply(pending, reply):
    """PURE. Returns [(item, verdict, why)] with verdict approved / declined / open."""
    per_item, rest = {}, []
    for line in re.split(r"[\n;]+", reply or ""):
        m = NUMBERED.match(line)
        if m and 1 <= int(m.group(1)) <= len(pending["items"]):
            per_item[int(m.group(1))] = m.group(2)
        elif line.strip():
            rest.append(line.strip())
    general = " ".join(rest)
    excepted = set()
    m = EXCEPT.search(general)
    if m:
        excepted = {int(x) for x in re.findall(r"\d{1,2}", m.group(2))}
        general = general[:m.start()]
    overall = verdict_of(general)
    results = []
    for item in pending["items"]:
        n = item["n"]
        if n in per_item:
            verdict, source, why = verdict_of(per_item[n]), per_item[n], "answered by number"
        elif n in excepted:
            verdict, source, why = "declined", general, "excluded by name in the reply"
        else:
            verdict, source, why = overall, general, "covered by the general answer"
        if verdict == "approved" and item.get("cap_usd") is not None:
            figures = money_figures(source)
            if figures and all(abs(f - float(item["cap_usd"])) > 0.005 for f in figures):
                verdict, why = "open", "the reply names a different amount than the cap shown; ask again with the new figure"
        results.append((item, verdict, why))
    return results


def apply_reply(record, reply, replied_at=None, now=None):
    """Save the answer to the pending ask. Returns (record, summary lines). Raises ValueError when
    there is nothing to answer or the reply decides nothing."""
    now = now or now_utc()
    pending = record.get("pending")
    if not pending:
        raise ValueError("nothing is pending for this run; run propose first")
    reply = (reply or "").strip()
    if not reply:
        raise ValueError("the reply is empty")
    when = parse_time(replied_at) if replied_at else now
    if when < parse_time(pending["proposed_at"]):
        raise ValueError("the reply is older than the ask it is supposed to answer")
    results = evaluate_reply(pending, reply)
    if all(verdict == "open" for _, verdict, _ in results):
        raise ValueError("the reply does not answer the ask (no yes, no refusal); the ask stays pending")
    expires = (when + dt.timedelta(hours=float(pending["ttl_hours"]))).isoformat()
    still_open, summary = [], []
    keep = [d for d in record["decisions"]
            if item_id(d) not in {item_id(i) for i, v, _ in results if v != "open"}]
    for item, verdict, why in results:
        if verdict == "open":
            still_open.append(item)
            summary.append("OPEN      %d. %s (%s)" % (item["n"], item["label"], why))
            continue
        decision = {k: v for k, v in item.items() if k != "n"}
        decision.update({"verdict": verdict, "quote": reply[:2000], "decided_at": when.isoformat(),
                         "expires_at": expires, "ask": pending["ask"], "token": pending["token"]})
        if decision["kind"] == "spend":
            decision["spent_usd"] = 0.0
        keep.append(decision)
        summary.append("%-9s %d. %s" % (verdict.upper(), item["n"], item["label"]))
    record["decisions"] = keep
    if pending["ask"] == "bundle":
        approved = {item_id(d) for d in keep if d["verdict"] == "approved"}
        missing = [k for k in BUNDLE_REQUIRED if k not in approved]
        if not still_open and not missing:
            record["bundle"] = {"recorded_at": when.isoformat(), "expires_at": expires, "token": pending["token"]}
            summary.append("BUNDLE RECORDED, valid until %s" % expires)
        else:
            record["bundle"] = None
            summary.append("BUNDLE NOT RECORDED: %s" % "; ".join(
                (["still open: %s" % ", ".join(str(i["n"]) for i in still_open)] if still_open else [])
                + (["required and not approved: %s" % ", ".join(missing)] if missing else [])))
    record["pending"] = dict(pending, items=still_open) if still_open else None
    return record, summary


def bundle_problem(record, now=None):
    """Why the up-front bundle does not cover this run right now, or None."""
    now = now or now_utc()
    bundle = record.get("bundle")
    if not bundle:
        return "no approval bundle is recorded for run %r (propose, show the message, record the reply)" % record.get("run")
    try:
        if parse_time(bundle["expires_at"]) <= now:
            return "the approval bundle for run %r expired at %s; propose it again" % (record.get("run"), bundle["expires_at"])
    except (KeyError, TypeError, ValueError):
        return "the approval bundle has no readable expiry"
    return None


def find_decision(record, kind, key, now=None):
    """(decision, None) when an approved, unexpired decision exists; else (None, reason)."""
    now = now or now_utc()
    for d in record.get("decisions") or []:
        if d.get("kind") == kind and str(d.get("key")) == str(key):
            if d.get("verdict") != "approved":
                return None, "%s:%s was declined; a declined item never counts" % (kind, key)
            try:
                if parse_time(d["expires_at"]) <= now:
                    return None, "%s:%s expired at %s" % (kind, key, d["expires_at"])
            except (KeyError, TypeError, ValueError):
                return None, "%s:%s has no readable expiry" % (kind, key)
            return d, None
    return None, "no approval is saved for %s:%s on run %r" % (kind, key, record.get("run"))


def spend_problem(record, provider, amount, now=None):
    """Why this spend is not covered, or None. The cap is cumulative for the run."""
    why = bundle_problem(record, now)
    if why:
        return why
    provider = str(provider or "").strip().lower()
    decision, why = find_decision(record, "spend", provider, now)
    if why:
        others = sorted(d["key"] for d in record["decisions"] if d.get("kind") == "spend" and d.get("verdict") == "approved")
        return why + (" (approved providers: %s; an approval for one provider never covers another)" % ", ".join(others) if others else "")
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return "the amount is not a number"
    if amount <= 0:
        return "the amount must be above zero"
    spent = float(decision.get("spent_usd") or 0)
    if spent + amount > float(decision["cap_usd"]) + 1e-9:
        return "%s: $%.2f already claimed + $%.2f asked is over the $%.2f cap; put the overrun in the exceptions digest" % (
            provider, spent, amount, float(decision["cap_usd"]))
    return None


def claim_spend(record, provider, amount, now=None):
    """Count a spend against its cap. Returns the problem, or None after adding it."""
    why = spend_problem(record, provider, amount, now)
    if why:
        return why
    decision, _ = find_decision(record, "spend", str(provider).strip().lower(), now)
    decision["spent_usd"] = round(float(decision.get("spent_usd") or 0) + float(amount), 4)
    return None


def evidence_matches(text, condition):
    """A non-empty file is not proof. The evidence must speak about the condition: it has to carry
    most of the condition's own key terms."""
    terms = {w for w in re.findall(r"[a-záéíóúñü0-9_]{4,}", (condition or "").lower())}
    if not terms:
        return False
    low = (text or "").lower()
    hit = sum(1 for t in terms if t in low)
    return hit / float(len(terms)) >= 0.6


def skip_problem(record, step, evidence_text, now=None):
    why = bundle_problem(record, now)
    if why:
        return why
    decision, why = find_decision(record, "skip_step", step, now)
    if why:
        return why
    if not evidence_matches(evidence_text, decision.get("condition")):
        return ("the skip of step %s was approved only if: %s. The evidence given does not show that condition held"
                % (step, decision.get("condition")))
    return None


def gate_words(gate):
    return [w for w in re.split(r"[^a-z0-9]+", str(gate).lower()) if len(w) >= 3]


def bypass_problem(record, gate, quote, quoted_at, now=None):
    """Why a quote does not authorise a logged false-positive bypass of this gate, or None."""
    gate = str(gate or "").strip().lower()
    if not gate or BYPASS_NEVER.search(gate):
        return "the gate %r can never be bypassed on a quote (suppression, hardening, pushes and sends are excluded)" % gate
    why = bundle_problem(record, now)
    if why:
        return why
    for key in ("policy", gate):
        _, why = find_decision(record, "false_positive_bypass", key, now)
        if why:
            return why
    quote = (quote or "").strip()
    if verdict_of(quote) != "approved":
        return "the quote is not an agreement"
    words = gate_words(gate)
    low = re.sub(r"[^a-z0-9]+", " ", quote.lower())
    if not words or not all(w in low for w in words):
        return "the quote does not name the gate %r; an unrelated yes does not bypass it" % gate
    try:
        if parse_time(quoted_at) <= parse_time(record["bundle"]["recorded_at"]):
            return "the quote is older than the approval bundle; it must be said after the bundle was recorded"
    except (TypeError, ValueError):
        return "the quote has no readable time (--quoted-at ISO)"
    return None


def copy_signoff_problem(record, campaign_id, action, live_status, live_fingerprint, leads_sha256=None, account=None, now=None):
    """Does the saved copy sign-off cover THIS action on THIS campaign right now? None = covered.

    This is read by ONE caller: the push wrapper, as its approval gate. No hook reads it, so it
    can never release a raw HTTP push or a direct MCP push, which skip suppression, cooldown and
    logging. live_status and live_fingerprint come from a read of the platform made by the caller;
    a missing value is a refusal."""
    if str(action).lower() != "push":
        return "the copy sign-off covers a DRAFT push only; %r (go-live, settings) is always its own approval" % action
    decision, why = find_decision(record, "copy_signoff_draft_push", "draft_push", now)
    if why:
        return why
    if str(campaign_id) not in [str(c) for c in decision.get("campaign_ids") or []]:
        return "campaign %s is not one of the campaigns named in the sign-off (%s)" % (
            campaign_id, ", ".join(map(str, decision.get("campaign_ids") or [])))
    status = str(live_status or "").upper()
    if status not in DRAFT_STATUSES:
        return "campaign %s is %s on the platform; the sign-off covers a push only while it is DRAFTED or PAUSED" % (
            campaign_id, status or "of unknown status")
    if not live_fingerprint or str(live_fingerprint) != str(decision.get("copy_fingerprint")):
        return "the copy fingerprint is not the one that was signed off (copy changed after sign-off, or could not be read)"
    if not leads_sha256 or str(leads_sha256) != str(decision.get("leads_sha256")):
        return "the leads file is not the file that was signed off (its hash differs, or was not given)"
    if not str(account or "").strip() or str(account).strip().lower() != str(decision.get("account") or "").strip().lower():
        return "the sending account %r is not the account named in the sign-off (%r)" % (account, decision.get("account"))
    return None


def go_live_problem(record, campaign_id, now=None):
    _, why = find_decision(record, "go_live", str(campaign_id), now)
    return why


def clamp_ttl(value, default, maximum):
    ttl = float(value if value is not None else default)
    if not 0 < ttl <= maximum:
        raise ValueError("--ttl-hours must be above 0 and at most %s" % maximum)
    return ttl


def sha_file(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def digest_text(record):
    rows = record.get("digest") or []
    if not rows:
        return ""
    lines = ["Exceptions digest for %s (%s): %d item(s). One reply covers them; answer in any words, or per number."
             % (record["run"], record.get("client") or "no client set", len(rows)), ""]
    for n, row in enumerate(rows, 1):
        count = " (%s)" % row["count"] if row.get("count") not in (None, "") else ""
        lines.append("%d. [%s]%s %s" % (n, row["type"], count, row["detail"]))
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument("--run", required=True, help="the campaign run this record belongs to")
        sp.add_argument("--state-dir", help="where the record lives (default CAMPAIGN_STATE_DIR or .claude/campaign-state)")
        return sp

    sp = add("propose", help="touchpoint 1: build the up-front bundle message")
    sp.add_argument("--client", required=True)
    sp.add_argument("--plan", required=True, help="JSON: scope, cohort_target, copy_author, caps, skips, contact_search, false_positive_gates")
    sp.add_argument("--ttl-hours", type=float)
    sp = add("propose-offer", help="touchpoint 2: offer plus 10 examples, only if new or changed")
    sp.add_argument("--offer-file", required=True)
    sp.add_argument("--examples-file", required=True, help="JSON array of exactly 10 rendered examples")
    sp.add_argument("--ttl-hours", type=float)
    sp = add("propose-signoff", help="touchpoint 3: final copy sign-off plus DRAFT push of the named campaigns")
    sp.add_argument("--campaign-ids", required=True, help="comma-separated platform campaign ids")
    sp.add_argument("--fingerprint", required=True, help="copy fingerprint from check-copy-variation.py")
    sp.add_argument("--leads-file", required=True, help="the exact leads file that will be pushed; its hash is part of the sign-off")
    sp.add_argument("--account", required=True, help="the sending account (platform client id, or 0 for your own account)")
    sp.add_argument("--ttl-hours", type=float)
    sp = add("propose-go-live", help="touchpoint 4: go-live of one campaign")
    sp.add_argument("--campaign-id", required=True)
    sp = add("record", help="save the human's reply to the pending ask")
    sp.add_argument("--reply")
    sp.add_argument("--reply-file")
    sp.add_argument("--replied-at", help="ISO time of the reply (default now)")
    sp = add("check", help="exit 0 when the action is covered, 2 with the reason when it is not")
    sp.add_argument("--kind", required=True, choices=BUNDLE_KINDS + SEPARATE_KINDS + ("bundle",))
    sp.add_argument("--key")
    sp.add_argument("--amount", type=float)
    sp.add_argument("--evidence", help="skip_step: file showing the skip condition held")
    sp.add_argument("--campaign-id")
    sp.add_argument("--action", default="push")
    sp.add_argument("--live-status")
    sp.add_argument("--live-fingerprint")
    sp.add_argument("--leads-file")
    sp.add_argument("--account")
    sp.add_argument("--offer-file")
    sp.add_argument("--examples-file")
    sp = add("claim-spend", help="count a spend against its provider cap")
    sp.add_argument("--provider", required=True)
    sp.add_argument("--amount", required=True, type=float)
    sp = add("bypass-check", help="does this quote authorise a logged false-positive bypass of this gate?")
    sp.add_argument("--gate", required=True)
    sp.add_argument("--quote", required=True)
    sp.add_argument("--quoted-at", required=True)
    add("status", help="what is recorded, what is open, what expired")
    sp = add("digest-add", help="touchpoint 5: add one exception; keep working on what it does not affect")
    sp.add_argument("--type", required=True, help="for example unsure_leads, spend_overrun, gate_false_positive")
    sp.add_argument("--detail", required=True)
    sp.add_argument("--count")
    add("digest-show", help="print the ONE digest message (empty when nothing tripped)")
    add("digest-clear", help="empty the digest after the human answered it")
    args = p.parse_args(argv)

    def refuse(message):
        print("REFUSED: %s" % message, file=sys.stderr)
        return 2

    try:
        record = load_record(args.run, args.state_dir)
    except (OSError, ValueError) as exc:
        return refuse("could not read the approvals record (%s). Unknown is not approved." % exc)
    now = now_utc()

    try:
        if args.cmd == "propose":
            with open(args.plan, encoding="utf-8") as fh:
                plan = json.load(fh)
            record["client"] = args.client
            record["pending"] = new_pending("bundle", build_bundle_items(plan),
                                            clamp_ttl(args.ttl_hours, BUNDLE_DEFAULT_TTL_HOURS, BUNDLE_MAX_TTL_HOURS), now)
        elif args.cmd == "propose-offer":
            with open(args.examples_file, encoding="utf-8") as fh:
                examples = json.load(fh)
            if not isinstance(examples, list) or len(examples) != OFFER_EXAMPLES:
                return refuse("the examples file must hold exactly %d rendered examples" % OFFER_EXAMPLES)
            record["pending"] = new_pending("offer_signoff", [{
                "kind": "offer_signoff", "key": "offer", "offer_sha256": sha_file(args.offer_file),
                "examples_sha256": sha_file(args.examples_file),
                "label": "the offer in %s and the %d examples in %s" % (
                    os.path.basename(args.offer_file), OFFER_EXAMPLES, os.path.basename(args.examples_file))}],
                clamp_ttl(args.ttl_hours, BUNDLE_DEFAULT_TTL_HOURS, BUNDLE_MAX_TTL_HOURS), now)
        elif args.cmd == "propose-signoff":
            ids = [x.strip() for x in args.campaign_ids.split(",") if x.strip()]
            if not ids or not all(re.match(r"^[A-Za-z0-9_-]+$", x) for x in ids):
                return refuse("--campaign-ids must list the exact campaign ids")
            leads_sha = sha_file(args.leads_file)
            label = ("sign off the final copy (fingerprint %s) and load the leads file %s (hash %s) into campaign(s) %s of sending "
                     "account %s, through the push wrapper, while they are DRAFTED or PAUSED. The wrapper may still skip leads "
                     "that fail its gates. This does not put anything live"
                     % (args.fingerprint[:12], os.path.basename(args.leads_file), leads_sha[:12], ", ".join(ids), args.account))
            record["pending"] = new_pending("copy_signoff_draft_push", [{
                "kind": "copy_signoff_draft_push", "key": "draft_push", "campaign_ids": ids,
                "copy_fingerprint": args.fingerprint, "leads_sha256": leads_sha, "account": str(args.account), "label": label}],
                clamp_ttl(args.ttl_hours, SIGNOFF_DEFAULT_TTL_HOURS, SIGNOFF_MAX_TTL_HOURS), now)
        elif args.cmd == "propose-go-live":
            record["pending"] = new_pending("go_live", [{
                "kind": "go_live", "key": str(args.campaign_id),
                "label": "put campaign %s live: it starts sending on its schedule" % args.campaign_id}], GO_LIVE_TTL_HOURS, now)
        if args.cmd.startswith("propose"):
            save_record(record, args.state_dir)
            print(ask_text(record))
            return 0

        if args.cmd == "record":
            reply = args.reply
            if args.reply_file:
                with open(args.reply_file, encoding="utf-8") as fh:
                    reply = fh.read()
            record, summary = apply_reply(record, reply, args.replied_at, now)
            save_record(record, args.state_dir)
            print("\n".join(summary))
            return 0

        if args.cmd == "check":
            if args.kind == "bundle":
                why = bundle_problem(record, now)
            elif args.kind == "spend":
                why = "--amount is required" if args.amount is None else spend_problem(record, args.key, args.amount, now)
            elif args.kind == "skip_step":
                text = ""
                if args.evidence:
                    with open(args.evidence, encoding="utf-8") as fh:
                        text = fh.read()
                why = skip_problem(record, args.key, text, now)
            elif args.kind == "copy_signoff_draft_push":
                why = copy_signoff_problem(record, args.campaign_id, args.action, args.live_status, args.live_fingerprint,
                                           sha_file(args.leads_file) if args.leads_file else None, args.account, now)
            elif args.kind == "go_live":
                why = go_live_problem(record, args.campaign_id or args.key, now)
            elif args.kind == "offer_signoff":
                decision, why = find_decision(record, "offer_signoff", "offer", now)
                if decision and (not args.offer_file or not args.examples_file
                                 or sha_file(args.offer_file) != decision.get("offer_sha256")
                                 or sha_file(args.examples_file) != decision.get("examples_sha256")):
                    why = "the offer or the examples changed since they were signed off (or the files were not given)"
            else:
                why = bundle_problem(record, now) or find_decision(record, args.kind, args.key, now)[1]
            if why:
                return refuse(why)
            print("COVERED: %s %s on run %s" % (args.kind, args.key or args.campaign_id or "", args.run))
            return 0

        if args.cmd == "claim-spend":
            why = claim_spend(record, args.provider, args.amount, now)
            if why:
                return refuse(why)
            save_record(record, args.state_dir)
            print("CLAIMED: $%.2f against %s on run %s" % (args.amount, args.provider, args.run))
            return 0

        if args.cmd == "bypass-check":
            why = bypass_problem(record, args.gate, args.quote, args.quoted_at, now)
            if why:
                return refuse(why)
            record.setdefault("bypass_log", []).append(
                {"gate": args.gate, "quote": args.quote[:500], "quoted_at": args.quoted_at, "logged_at": now.isoformat()})
            save_record(record, args.state_dir)
            print("COVERED: logged false-positive bypass of %s on run %s" % (args.gate, args.run))
            return 0

        if args.cmd == "status":
            why = bundle_problem(record, now)
            print("run %s, client %s" % (record["run"], record.get("client") or "(not set)"))
            print("bundle: %s" % (why or "recorded, valid until %s" % record["bundle"]["expires_at"]))
            for d in record["decisions"]:
                _, dead = find_decision(record, d["kind"], d["key"], now)
                extra = " spent $%.2f of $%.2f" % (d.get("spent_usd") or 0, d["cap_usd"]) if d["kind"] == "spend" else ""
                print("  %-8s %s%s%s" % (d["verdict"], item_id(d), extra, "  [EXPIRED]" if dead and "expired" in dead else ""))
            if record.get("pending"):
                print("pending ask %s: %d item(s) open" % (record["pending"]["token"], len(record["pending"]["items"])))
            print("exceptions digest: %d item(s)" % len(record.get("digest") or []))
            return 0

        if args.cmd == "digest-add":
            record["digest"].append({"type": args.type, "detail": args.detail, "count": args.count, "at": now.isoformat()})
            save_record(record, args.state_dir)
            print("added to the exceptions digest (%d item(s)). Carry on with the work this does not affect." % len(record["digest"]))
            return 0
        if args.cmd == "digest-show":
            text = digest_text(record)
            print(text or "Nothing tripped. No digest to send.")
            return 0
        if args.cmd == "digest-clear":
            record["digest"] = []
            save_record(record, args.state_dir)
            print("digest cleared")
            return 0
    except (OSError, ValueError) as exc:
        return refuse(str(exc))
    return 0


if __name__ == "__main__":
    sys.exit(main())
