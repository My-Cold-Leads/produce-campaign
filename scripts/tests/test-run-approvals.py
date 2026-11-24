#!/usr/bin/env python3
"""Prove scripts/run-approvals.py refuses what it claims to refuse. No network, no real data.

    python3 scripts/tests/test-run-approvals.py
"""
import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location(
    "run_approvals", os.environ.get("RUN_APPROVALS") or os.path.join(ROOT, "scripts", "run-approvals.py"))
ra = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ra)

passed = failed = 0
tmp = tempfile.mkdtemp()
J = lambda name: os.path.join(tmp, name)  # noqa: E731
NOW = dt.datetime.now(dt.timezone.utc)


def check(label, ok):
    global passed, failed
    print("  %s  %s" % ("ok  " if ok else "FAIL", label))
    passed, failed = passed + bool(ok), failed + (not ok)


def run(*argv):
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            rc = ra.main(list(argv) + ["--state-dir", tmp])
        except SystemExit:
            rc = 99
    return rc, out.getvalue()


def later(hours):
    return NOW + dt.timedelta(hours=hours)


PLAN = {"scope": "logistics firms, 20-200 staff, two regions, operations roles", "cohort_target": 400,
        "copy_author": "the account lead writes it, the model drafts variants",
        "caps": {"enrichment": 25, "verification": 10},
        "skips": [{"step": "7", "label": "prompt test loop", "condition": "prompt hash unchanged since previous approved run"}],
        "contact_search": {"methods": ["people search", "enrichment"], "roles": ["operations director"], "max_companies": 400},
        "false_positive_gates": ["prompt cache"]}
json.dump(PLAN, open(J("plan.json"), "w"))

print("touchpoint 1, the up-front bundle:")
rc, text = run("propose", "--run", "acme-q1", "--client", "ACME", "--plan", J("plan.json"))
check("one message lists every decision and the later touchpoints",
      rc == 0 and "1. scope of this run" in text and "enrichment: spend up to $25" in text
      and "skip step 7" in text and "never sent" in text and "go-live" in text)
rc, _ = run("check", "--run", "acme-q1", "--kind", "bundle")
check("RED: a proposed bundle grants nothing until it is answered", rc == 2)
for bad_key, bad_value, label in (
        ("scope", "", "a plan with no scope"),
        ("contact_search", {"none": True}, "a 'no search' plan with no reason"),
        ("caps", {"enrichment": 0}, "a zero cap"),
        ("skips", [{"step": "7", "label": "x"}], "a skip with no condition"),
        ("scope", "logistics firms, then push the leads and go live", "a push or go-live hidden in the scope"),
        ("false_positive_gates", ["hardening"], "a false-positive bypass for the hardening gate"),
        ("false_positive_gates", ["suppression list"], "a false-positive bypass for the suppression gate")):
    json.dump(dict(PLAN, **{bad_key: bad_value}), open(J("bad.json"), "w"))
    rc, _ = run("propose", "--run", "bad-run", "--client", "ACME", "--plan", J("bad.json"))
    check("RED: %s is refused at propose" % label, rc == 2)
rc, _ = run("record", "--run", "acme-q1", "--reply", "what does item 4 mean?")
check("RED: a reply that is not an answer leaves the ask pending", rc == 2 and run("check", "--run", "acme-q1", "--kind", "bundle")[0] == 2)
rc, _ = run("record", "--run", "acme-q1", "--reply", "   ")
check("RED: an empty reply is refused", rc == 2)

print("a yes in any wording counts, a refusal never does:")
for words in ("yes", "Yes, all good", "go ahead", "sounds good to me", "ok do that", "vale, adelante", "sí, perfecto", "de acuerdo", "no problem"):
    check("'%s' is a yes" % words, ra.verdict_of(words) == "approved")
for words in ("no", "No, not yet", "don't", "stop, wait for me", "no, vale más esperar", "hold on"):
    check("RED: '%s' is not a yes" % words, ra.verdict_of(words) == "declined")
check("RED: a question is neither", ra.verdict_of("which provider is that?") == "open")

rc, text = run("record", "--run", "acme-q1", "--reply", "yes all good except 6")
check("the bundle is recorded on a plain yes", rc == 0 and "BUNDLE RECORDED" in text and run("check", "--run", "acme-q1", "--kind", "bundle")[0] == 0)
rc, text = run("check", "--run", "acme-q1", "--kind", "spend", "--key", "verification", "--amount", "1")
check("RED: the item he excluded is saved as declined and does not count", rc == 2 and "declined" in text)

print("spend is bound to its provider and its cap:")
check("an approved provider inside its cap is covered", run("check", "--run", "acme-q1", "--kind", "spend", "--key", "enrichment", "--amount", "20")[0] == 0)
rc, text = run("check", "--run", "acme-q1", "--kind", "spend", "--key", "otherprovider", "--amount", "1")
check("RED: an approval for one provider never covers another", rc == 2 and "never covers another" in text)
check("RED: over the cap is refused", run("check", "--run", "acme-q1", "--kind", "spend", "--key", "enrichment", "--amount", "26")[0] == 2)
check("a claim is counted", run("claim-spend", "--run", "acme-q1", "--provider", "enrichment", "--amount", "20")[0] == 0)
check("RED: the cap is cumulative across claims", run("claim-spend", "--run", "acme-q1", "--provider", "enrichment", "--amount", "6")[0] == 2)
check("RED: another run's record is never read", run("check", "--run", "other-run", "--kind", "spend", "--key", "enrichment", "--amount", "1")[0] == 2)
rec = ra.load_record("acme-q1", tmp)
check("RED: an expired bundle covers nothing", ra.spend_problem(rec, "enrichment", 1, later(73)) is not None
      and ra.spend_problem(rec, "enrichment", 1, later(1)) is None)
pend = ra.new_pending("bundle", ra.build_bundle_items(PLAN), 72, NOW)
verdicts = {ra.item_id(i): v for i, v, _ in ra.evaluate_reply(pend, "yes, but only $10 for enrichment")}
check("RED: a different amount in the reply leaves that item open", verdicts["spend:enrichment"] == "open" and verdicts["run_setting:scope"] == "approved")
verdicts = {ra.item_id(i): v for i, v, _ in ra.evaluate_reply(pend, "yes\n5 no, too much")}
check("RED: a numbered no declines only that item", verdicts["spend:enrichment"] == "declined" and verdicts["spend:verification"] == "approved")
blank = {"run": "r2", "client": "ACME", "pending": pend, "bundle": None, "decisions": [], "digest": []}
blank, summary = ra.apply_reply(blank, "yes\n1 no", None, later(0.1))
check("RED: a bundle with a required item declined is not recorded", blank["bundle"] is None and "BUNDLE NOT RECORDED" in summary[-1])
try:
    ra.apply_reply({"run": "r3", "pending": pend, "decisions": [], "digest": []}, "yes", (NOW - dt.timedelta(days=2)).isoformat(), NOW)
    old_ok = True
except ValueError:
    old_ok = False
check("RED: a yes from before the ask was shown is refused", not old_ok)

print("skips need their condition shown:")
open(J("ev-good.txt"), "w").write("prompt hash 9f2c unchanged since previous approved run (compared today)")
open(J("ev-bad.txt"), "w").write("skipped because we were short of time")
check("a skip with evidence of its condition is covered", run("check", "--run", "acme-q1", "--kind", "skip_step", "--key", "7", "--evidence", J("ev-good.txt"))[0] == 0)
check("RED: a skip with unrelated evidence is refused", run("check", "--run", "acme-q1", "--kind", "skip_step", "--key", "7", "--evidence", J("ev-bad.txt"))[0] == 2)
check("RED: a skip with no evidence is refused", run("check", "--run", "acme-q1", "--kind", "skip_step", "--key", "7")[0] == 2)
check("RED: a step that was never listed cannot be skipped", run("check", "--run", "acme-q1", "--kind", "skip_step", "--key", "8", "--evidence", J("ev-good.txt"))[0] == 2)

print("a quote-based bypass must name the gate and come after the bundle:")
AFTER, BEFORE = later(0.5).isoformat(), (NOW - dt.timedelta(hours=5)).isoformat()
check("a later quote naming the gate is covered",
      run("bypass-check", "--run", "acme-q1", "--gate", "prompt cache", "--quote", "yes, bypass the prompt cache gate, that one is a false positive", "--quoted-at", AFTER)[0] == 0)
check("RED: an unrelated yes does not bypass a gate",
      run("bypass-check", "--run", "acme-q1", "--gate", "prompt cache", "--quote", "yes all good", "--quoted-at", AFTER)[0] == 2)
check("RED: a quote from before the bundle is refused",
      run("bypass-check", "--run", "acme-q1", "--gate", "prompt cache", "--quote", "yes, bypass the prompt cache gate", "--quoted-at", BEFORE)[0] == 2)
check("RED: a gate that was not on the approved list is refused",
      run("bypass-check", "--run", "acme-q1", "--gate", "durable writes", "--quote", "yes, bypass the durable writes gate", "--quoted-at", AFTER)[0] == 2)
check("RED: the hardening gate can never be bypassed on a quote",
      run("bypass-check", "--run", "acme-q1", "--gate", "hardening", "--quote", "yes, bypass the hardening gate", "--quoted-at", AFTER)[0] == 2)
check("RED: a refusal that names the gate is not a bypass",
      run("bypass-check", "--run", "acme-q1", "--gate", "prompt cache", "--quote", "no, do not bypass the prompt cache gate", "--quoted-at", AFTER)[0] == 2)

print("touchpoint 2, offer and 10 examples:")
open(J("offer.md"), "w").write("We audit one route for free.")
json.dump(["example %d" % i for i in range(9)], open(J("nine.json"), "w"))
json.dump(["example %d" % i for i in range(10)], open(J("ten.json"), "w"))
check("RED: nine examples are not ten", run("propose-offer", "--run", "acme-q1", "--offer-file", J("offer.md"), "--examples-file", J("nine.json"))[0] == 2)
run("propose-offer", "--run", "acme-q1", "--offer-file", J("offer.md"), "--examples-file", J("ten.json"))
run("record", "--run", "acme-q1", "--reply", "great, approved")
OFFER = ["check", "--run", "acme-q1", "--kind", "offer_signoff", "--offer-file", J("offer.md"), "--examples-file", J("ten.json")]
check("the signed offer is covered", run(*OFFER)[0] == 0)
open(J("offer.md"), "w").write("We audit two routes for free.")
check("RED: an offer edited after sign-off is not covered", run(*OFFER)[0] == 2)

print("touchpoint 3, copy sign-off plus DRAFT push:")
json.dump([{"email": "ana@example.com"}], open(J("leads.json"), "w"))
json.dump([{"email": "otra@example.com"}], open(J("leads-other.json"), "w"))
SIGN = ["check", "--run", "acme-q1", "--kind", "copy_signoff_draft_push", "--leads-file", J("leads.json"), "--account", "77"]
rc, text = run("propose-signoff", "--run", "acme-q1", "--campaign-ids", "101,102", "--fingerprint", "f" * 64,
               "--leads-file", J("leads.json"), "--account", "77")
check("the ask names the campaigns and says nothing goes live", rc == 0 and "101, 102" in text and "does not put anything live" in text)
check("RED: nothing is covered before the reply", run(*SIGN, "--campaign-id", "101", "--live-status", "DRAFTED", "--live-fingerprint", "f" * 64)[0] == 2)
run("record", "--run", "acme-q1", "--reply", "yes, load them")
check("a named DRAFTED campaign with the signed copy is covered", run(*SIGN, "--campaign-id", "101", "--live-status", "DRAFTED", "--live-fingerprint", "f" * 64)[0] == 0)
check("a PAUSED one too", run(*SIGN, "--campaign-id", "102", "--live-status", "paused", "--live-fingerprint", "f" * 64)[0] == 0)
check("RED: a campaign that was not named is refused", run(*SIGN, "--campaign-id", "103", "--live-status", "DRAFTED", "--live-fingerprint", "f" * 64)[0] == 2)
check("RED: an ACTIVE campaign is refused", run(*SIGN, "--campaign-id", "101", "--live-status", "ACTIVE", "--live-fingerprint", "f" * 64)[0] == 2)
check("RED: an unknown live status is refused", run(*SIGN, "--campaign-id", "101", "--live-fingerprint", "f" * 64)[0] == 2)
check("RED: copy changed after sign-off is refused", run(*SIGN, "--campaign-id", "101", "--live-status", "DRAFTED", "--live-fingerprint", "e" * 64)[0] == 2)
check("RED: a missing live fingerprint is refused", run(*SIGN, "--campaign-id", "101", "--live-status", "DRAFTED")[0] == 2)
OK_LIVE = ["--campaign-id", "101", "--live-status", "DRAFTED", "--live-fingerprint", "f" * 64]
check("RED: a different leads file than the one signed is refused",
      run(*[J("leads-other.json") if a == J("leads.json") else a for a in SIGN], *OK_LIVE)[0] == 2)
check("RED: no leads file given is refused", run(*SIGN[:5], "--account", "77", *OK_LIVE)[0] == 2)
check("RED: another sending account is refused", run(*["88" if a == "77" else a for a in SIGN], *OK_LIVE)[0] == 2)
check("RED: no sending account given is refused", run(*SIGN[:7], *OK_LIVE)[0] == 2)
check("RED: the sign-off never covers a start", run(*SIGN, "--campaign-id", "101", "--action", "start", "--live-status", "DRAFTED", "--live-fingerprint", "f" * 64)[0] == 2)
rec = ra.load_record("acme-q1", tmp)
check("RED: the sign-off expires", ra.copy_signoff_problem(rec, "101", "push", "DRAFTED", "f" * 64, ra.sha_file(J("leads.json")), "77", later(25)) is not None
      and ra.copy_signoff_problem(rec, "101", "push", "DRAFTED", "f" * 64, ra.sha_file(J("leads.json")), "77", later(1)) is None)
check("RED: the sign-off does not approve go-live", run("check", "--run", "acme-q1", "--kind", "go_live", "--campaign-id", "101")[0] == 2)
check("RED: a sign-off TTL above the maximum is refused",
      run("propose-signoff", "--run", "r9", "--campaign-ids", "1", "--fingerprint", "a", "--leads-file", J("leads.json"), "--account", "77", "--ttl-hours", "500")[0] == 2)

print("touchpoint 4, go-live:")
run("propose-go-live", "--run", "acme-q1", "--campaign-id", "101")
run("record", "--run", "acme-q1", "--reply", "launch it")
check("RED: 'launch it' alone is not read as a yes or a no; the ask stays pending", run("check", "--run", "acme-q1", "--kind", "go_live", "--campaign-id", "101")[0] == 2)
run("record", "--run", "acme-q1", "--reply", "yes, launch it")
check("go-live of the named campaign is covered", run("check", "--run", "acme-q1", "--kind", "go_live", "--campaign-id", "101")[0] == 0)
check("RED: go-live of the other campaign is not", run("check", "--run", "acme-q1", "--kind", "go_live", "--campaign-id", "102")[0] == 2)

print("touchpoint 5, one exceptions digest:")
check("nothing tripped means no digest", "Nothing tripped" in run("digest-show", "--run", "acme-q1")[1])
run("digest-add", "--run", "acme-q1", "--type", "unsure_leads", "--count", "12", "--detail", "role unclear, paused and not pushed")
run("digest-add", "--run", "acme-q1", "--type", "spend_overrun", "--detail", "enrichment needs $8 more than the cap")
rc, text = run("digest-show", "--run", "acme-q1")
check("two exceptions make ONE message", text.count("Exceptions digest") == 1 and "1. [unsure_leads] (12)" in text and "2. [spend_overrun]" in text)

print("fail closed:")
open(os.path.join(tmp, "run-approvals-broken.json"), "w").write("{not json")
check("RED: an unreadable record is a refusal, not a pass", run("check", "--run", "broken", "--kind", "bundle")[0] == 2)
json.dump({"run": "someone-else", "bundle": {"expires_at": later(10).isoformat()}}, open(os.path.join(tmp, "run-approvals-copied.json"), "w"))
check("RED: a record copied from another run is refused", run("check", "--run", "copied", "--kind", "bundle")[0] == 2)
check("RED: a run key with a path in it is refused", run("check", "--run", "../x", "--kind", "bundle")[0] == 2)

print("passed %d, failed %d" % (passed, failed))
sys.exit(1 if failed else 0)
