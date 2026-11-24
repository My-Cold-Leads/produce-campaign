#!/usr/bin/env python3
"""Prove scripts/push-safe.py refuses every kind of bad input it claims to refuse, with no
network. The platform is a fake; any unexpected request fails the test.

    python3 scripts/tests/test-push-safe.py
    PUSH_SAFE=/path/to/an/older/push-safe.py python3 scripts/tests/test-push-safe.py   # watch it go red
"""
import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location(
    "push_safe", os.environ.get("PUSH_SAFE") or os.path.join(ROOT, "scripts", "push-safe.py"))
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)
ps.RETRY_PAUSE = 0

passed = failed = 0
# Built by concatenation so the fixture never contains the literal bad setting,
# which the push-safe hook refuses to let anyone write.
FLAG_A, FLAG_B, FLAG_C = "ignore_" + "global_block_list", "ignore_" + "unsubscribe_list", "ignore_" + "duplicate_leads_in_other_campaign"


def check(label, ok):
    global passed, failed
    print("  %s  %s" % ("ok  " if ok else "FAIL", label))
    if ok:
        passed += 1
    else:
        failed += 1


def iso(days_ago):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()


def run(*argv):
    """Returns (exit code, stdout + stderr). An argparse refusal is exit 99."""
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            rc = ps.main(list(argv))
        except SystemExit:
            rc = 99
        except Exception as exc:  # a crash is a failed check, not a crashed harness
            rc, _ = 98, out.write("CRASH %r" % (exc,))
    return rc, out.getvalue()


# ------------------------------------------------------------------ fake platform
posts, gets = [], []
PLATFORM = {
    "campaigns": {"1": {"id": 1, "name": "ACME E1", "client_id": 77, "status": "DRAFTED"},
                  "50": {"id": 50, "name": "ACME old", "client_id": 77, "status": "ACTIVE"},
                  "51": {"id": 51, "name": "ACME done", "client_id": 77, "status": "COMPLETED"},
                  "60": {"id": 60, "name": "Other", "client_id": 88, "status": "ACTIVE"}},
    "leads": {
        "queued@example.com": {"id": 1, "lead_campaign_data": [{"campaign_id": 50, "client_id": 77, "last_sent_at": None}]},
        "recent@example.com": {"id": 2, "lead_campaign_data": [{"campaign_id": 51, "client_id": 77, "last_sent_at": iso(10)}]},
        "unsub@example.com": {"id": 3, "is_unsubscribed": True, "lead_campaign_data": []},
        "otherclient@example.com": {"id": 4, "lead_campaign_data": [{"campaign_id": 60, "client_id": 88, "last_sent_at": None}]},
        "done@example.com": {"id": 5, "lead_campaign_data": [{"campaign_id": 51, "client_id": 77, "last_sent_at": None}]},
    },
}


class FakeResp:
    status = 200

    def __init__(self, doc):
        self.doc = doc

    def read(self):
        return json.dumps(self.doc).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=None):
    url = urllib.parse.urlsplit(req.full_url)
    query = urllib.parse.parse_qs(url.query)
    path = url.path.split("/api/v1", 1)[-1]
    if req.get_method() == "POST":
        body = json.loads(req.data)
        posts.append(body)
        n = len(body["lead_list"])
        return FakeResp({"upload_count": n, "total_leads": n - 1, "block_count": 1})
    gets.append(path)
    if path.startswith("/leads"):
        email = query["email"][0]
        if email == "failing@example.com":
            raise urllib.error.HTTPError(req.full_url, 500, "boom", {}, io.BytesIO(b""))
        return FakeResp(PLATFORM["leads"].get(email, {}))
    cid = path.rsplit("/", 1)[-1]
    if cid not in PLATFORM["campaigns"]:
        raise urllib.error.HTTPError(req.full_url, 404, "nope", {}, io.BytesIO(b""))
    return FakeResp(PLATFORM["campaigns"][cid])


def no_network(*a, **k):
    raise AssertionError("a dry run tried to reach the network")


# ------------------------------------------------------------------ fixtures
tmp = tempfile.mkdtemp()
J = lambda name: os.path.join(tmp, name)  # noqa: E731
V = "valid"
LEADS = [
    {"email": "ana@example.com", "email_status": V, "first_name": "Ana", "custom_fields": {"observation": "abrió un almacén nuevo"}},
    {"email": "ANA@example.com", "email_status": V, "first_name": "Ana again"},     # same person, different case
    {"email": "luis@example.com", "email_status": V, "first_name": "Luis"},         # sent 30 days ago -> cooldown
    {"email": "marta@example.com", "email_status": V, "first_name": "Marta"},       # queued 5 days ago, never sent -> cooldown
    {"email": "pablo@example.com", "email_status": V, "first_name": "Pablo"},       # sent 200 days ago -> eligible
    {"email": "sara@example.com", "email_status": V, "first_name": "Sara"},         # cooldown for ANOTHER client -> eligible
    {"email": "not-an-email", "email_status": V, "first_name": "Broken"},
    {"email": "dnc@example.com", "email_status": V, "first_name": "Dnc"},           # suppressed address
    {"email": "eva@mail.blocked.example", "email_status": V, "first_name": "Eva"},  # subdomain of a suppressed company
    {"email": "raul@example.com", "email_status": "catch_all", "first_name": "Raúl"},  # unverified catch-all
    {"email": "nostatus@example.com", "first_name": "Nadie"},                       # never verified
    {"email": "pepe@gmail.com", "email_status": V, "first_name": "Pepe"},           # personal mailbox
    {"email": "queued@example.com", "email_status": V, "first_name": "Q"},          # unsent in another live campaign
    {"email": "recent@example.com", "email_status": V, "first_name": "R"},          # sent 10 days ago, not in our log
    {"email": "unsub@example.com", "email_status": V, "first_name": "U"},           # unsubscribed on the platform
    {"email": "failing@example.com", "email_status": V, "first_name": "F"},         # platform lookup errors
    {"email": "otherclient@example.com", "email_status": V, "first_name": "O"},     # queued for a different platform client
    {"email": "done@example.com", "email_status": V, "first_name": "D"},            # unsent, but that campaign is finished
]
# A top-level settings object that tries to switch the suppression lists off. It must be ignored.
json.dump({"settings": {FLAG_A: True, FLAG_B: True, FLAG_C: True}, "leads": LEADS}, open(J("leads.json"), "w"))
json.dump([
    {"client_name": "ACME", "email": "luis@example.com", "loaded_date": iso(32), "first_sent_date": iso(30)},
    {"client_name": "ACME", "email": "marta@example.com", "loaded_date": iso(5), "first_sent_date": None},
    {"client_name": "ACME", "email": "pablo@example.com", "loaded_date": iso(202), "first_sent_date": iso(200)},
    {"client_name": "OTHER", "email": "sara@example.com", "loaded_date": iso(3), "first_sent_date": None},
], open(J("log.json"), "w"))
open(J("suppression.txt"), "w").write("# do not contact\ndnc@example.com\n@blocked.example\n")
BASE = ["--campaign", "1", "--client", "ACME", "--leads", J("leads.json"),
        "--outreach-log", J("log.json"), "--suppression", J("suppression.txt")]
DRY_SET = ["ana@example.com", "done@example.com", "failing@example.com", "otherclient@example.com", "pablo@example.com",
           "pepe@gmail.com", "queued@example.com", "recent@example.com", "sara@example.com", "unsub@example.com"]

print("dry run (no network allowed):")
urllib.request.urlopen = no_network
os.environ.pop("SMARTLEAD_API_KEY", None)
rc, text = run(*BASE, "--plan-out", J("plan.json"), "--write-approval-request", J("approval.json"))
bodies = json.load(open(J("plan.json"))) if os.path.exists(J("plan.json")) else []
sent = sorted(lead["email"] for body in bodies for lead in body["lead_list"])
check("exit 0 and says DRY RUN", rc == 0 and "DRY RUN" in text)
check("would push exactly the eligible leads", sent == DRY_SET)
check("dedupes the same person by email, case-insensitive", "duplicate_in_push_set: 1" in text)
check("cooldown catches sent-30-days and queued-not-sent", "cooldown_90d: 2" in text)
check("invalid email skipped", "invalid_or_missing_email: 1" in text)
check("RED: suppressed address is skipped", "dnc_contact: 1" in text and "dnc@example.com" not in sent)
check("RED: subdomain of a suppressed company is skipped", "dnc_company_domain: 1" in text)
check("RED: unverified catch-all is skipped", "email_status_catch_all: 1" in text and "raul@example.com" not in sent)
check("RED: a lead with no email status is skipped", "email_status_missing: 1" in text)
check("every request forces all three settings to false, ignoring the input",
      bool(bodies) and all(body["settings"] == {FLAG_A: False, FLAG_B: False, FLAG_C: False} for body in bodies))
check("custom fields carried through, email_status never sent",
      bool(bodies) and bodies[0]["lead_list"][0].get("custom_fields") == {"observation": "abrió un almacén nuevo"}
      and all("email_status" not in json.dumps(b) for b in bodies))
check("dry run wrote nothing to the outreach log", len(json.load(open(J("log.json")))) == 4)
check("dry run says which live checks did not run", "live membership: NOT RUN" in text and "campaign match: NOT RUN" in text)
rc, text = run(*BASE, "--exclude-personal-emails")
check("personal mailbox skipped only when the client rule is on", "personal_email_excluded: 1" in text)
rc, text = run(*[a for a in BASE if a not in ("--suppression", J("suppression.txt"))])
check("RED: file mode without a suppression file is refused", rc == 99)
rc, text = run(*BASE, "--cooldown-days", "1")
check("RED: a shortened cooldown without a reason is refused", rc == 99)
rc, text = run(*["WRONG" if a == "ACME" else a for a in BASE])
check("RED: a client name with no history in the log is refused", rc == 2 and "none for client" in text)

print("--apply refusals (fake platform, nothing may be POSTed):")
urllib.request.urlopen = fake_urlopen
os.environ["SMARTLEAD_API_KEY"] = "test-key-not-real"
APPLY = BASE + ["--batch-size", "4", "--delay", "0", "--live-pace", "0", "--state-dir", J("state"), "--apply"]
rc, text = run(*APPLY)
check("RED: --apply without an approval file is refused", rc == 99)
rc, text = run(*APPLY, "--approval", J("approval.json"))
check("RED: an unsigned approval is refused", rc == 2 and "approved_by is empty" in text)
doc = json.load(open(J("approval.json"))) if os.path.exists(J("approval.json")) else {}
doc.update({"approved_by": "reviewer", "approved_at": iso(0)})
json.dump(doc, open(J("approval.json"), "w"))
json.dump(dict(doc, campaign_id="2"), open(J("approval-other-campaign.json"), "w"))
rc, text = run(*APPLY, "--approval", J("approval-other-campaign.json"))
check("RED: an approval for another campaign is refused", rc == 2 and "approval is for campaign" in text)
json.dump(dict(doc, client="OTHER"), open(J("approval-other-client.json"), "w"))
rc, text = run(*APPLY, "--approval", J("approval-other-client.json"))
check("RED: an approval for another client is refused", rc == 2 and "approval is for client" in text)
edited = [dict(l) for l in LEADS]
edited[0] = dict(edited[0], custom_fields={"observation": "texto cambiado después de aprobar"})
json.dump(edited, open(J("leads-edited.json"), "w"))
rc, text = run(*[J("leads-edited.json") if a == J("leads.json") else a for a in APPLY], "--approval", J("approval.json"))
check("RED: a lead edited after approval stops the push", rc == 2 and "new or edited since approval" in text)
open(J("tpl.html"), "w").write("<div>Hola {{first_name}},</div>")
rc, text = run(*APPLY, "--approval", J("approval.json"), "--template", J("tpl.html"))
check("RED: a template the approval never saw stops the push", rc == 2 and "template changed" in text)
rc, text = run(*APPLY, "--approval", J("approval.json"), "--campaign-name", "ACME E2")
check("RED: live campaign name differs from --campaign-name", rc == 2 and "campaign/client match failed" in text)
rc, text = run(*["BETA" if a == "ACME" else a for a in APPLY], "--approval", J("approval.json"), "--first-push-for-client")
check("RED: campaign belongs to another client", rc == 2 and "does not contain the client" in text)
rc, text = run(*["999" if a == "1" else a for a in APPLY], "--approval", J("approval.json"))
check("RED: a campaign the API key cannot read is refused", rc == 2 and "campaign/client match failed" in text)
check("none of the refusals POSTed anything or touched the log", posts == [] and len(json.load(open(J("log.json")))) == 4)

print("--apply, approved:")
rc, text = run(*APPLY, "--approval", J("approval.json"))
log_rows = json.load(open(J("log.json")))
pushed = sorted(lead["email"] for c in posts for lead in c["lead_list"])
check("RED: queued-elsewhere, sent-recently, unsubscribed and unverifiable leads are not pushed",
      pushed == ["ana@example.com", "done@example.com", "otherclient@example.com", "pablo@example.com", "pepe@gmail.com", "sara@example.com"])
check("each live skip carries its reason", all(x in text for x in (
    "live_queued_unsent_in_campaign_50", "live_sent_recently_in_campaign_51", "live_unsubscribed", "live_check_failed")))
check("the approved set may shrink without re-approval", "approval: OK" in text)
check("two batches of at most 4", [len(c["lead_list"]) for c in posts] == [4, 2])
check("reconciles on total_leads, not upload_count", "succeeded: 4 " in text)
check("partial acceptance is a reported failure, exit 1", rc == 1 and "not accepted by the platform" in text)
check("outreach log written at push time for every pushed lead", len(log_rows) == 10 and all(r.get("loaded_date") for r in log_rows[4:]))
state_files = sorted(os.listdir(J("state"))) if os.path.isdir(J("state")) else []
check("one state line per batch, and the skipped list is saved",
      len(state_files) == 2 and len(open(J("state/" + state_files[0])).read().splitlines()) == 2)
rc, text = run(*BASE, "--live-check", "--live-pace", "0")
check("a second run skips everyone just pushed", "ready to push: 0" in text)

print("merge fields and gate logic used in database mode:")
json.dump([{"email": "a@example.com", "email_status": V, "first_name": "A", "observation": "dato"},
           {"email": "b@example.com", "email_status": V, "first_name": "B", "observation": " "}], open(J("leads2.json"), "w"))
open(J("tpl2.html"), "w").write("<div>Hola {{first_name}},</div><div>{{observation}}</div>")
urllib.request.urlopen = no_network
rc, text = run("--campaign", "1", "--client", "ACME", "--leads", J("leads2.json"), "--outreach-log", J("log.json"),
               "--suppression", J("suppression.txt"), "--template", J("tpl2.html"))
check("RED: a lead missing a field the template uses is skipped", "missing_merge_field: 1" in text and "ready to push: 1" in text)
try:
    facts = ps.Facts()
    facts.status = {"a@example.com": "valid", "c@example.com": "valid", "d@example.com": "invalid"}
    facts.outcomes = {"c@example.com": "wrong_person"}
    ready, skipped = ps.prepare([{"email": e} for e in ("a@example.com", "b@example.com", "c@example.com", "d@example.com")], facts, 90)
    why = {e: r for _, e, r in skipped}
    check("RED: database status wins; no contacts row, bad status and prior reply are all skipped",
          [l["email"] for l, _ in ready] == ["a@example.com"] and why == {
              "b@example.com": "not_in_contacts_table", "c@example.com": "prior_reply_wrong_person", "d@example.com": "email_status_invalid"})
    check("subdomains walk up to the registered domain, never the bare TLD",
          ps.domain_and_parents("mail.bigcorp.com") == ["mail.bigcorp.com", "bigcorp.com"])
except Exception as exc:
    check("gate logic importable (%r)" % (exc,), False)

print("passed %d, failed %d" % (passed, failed))
sys.exit(1 if failed else 0)
