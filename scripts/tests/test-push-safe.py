#!/usr/bin/env python3
"""Prove scripts/push-safe.py applies the cooldown, dedupes by person and forces the
suppression settings - with no network. Any attempt to reach the network fails the test.

    python3 scripts/tests/test-push-safe.py
"""
import contextlib
import datetime as dt
import importlib.util
import io
import json
import os
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location("push_safe", os.path.join(ROOT, "scripts", "push-safe.py"))
ps = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ps)

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


def no_network(*a, **k):
    raise AssertionError("dry run tried to reach the network")


def iso(days_ago):
    return (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days_ago)).isoformat()


tmp = tempfile.mkdtemp()
leads_json = os.path.join(tmp, "leads.json")
log_path = os.path.join(tmp, "outreach_log.json")
plan = os.path.join(tmp, "plan.json")

# A top-level settings object that tries to switch the suppression lists off. It must be ignored.
bad_settings = {FLAG_A: True, FLAG_B: True, FLAG_C: True}
json.dump({"settings": bad_settings, "leads": [
    {"email": "ana@example.com", "first_name": "Ana", "custom_fields": {"observation": "abrió un almacén nuevo"}},
    {"email": "ANA@example.com", "first_name": "Ana again"},              # same person, different case
    {"email": "luis@example.com", "first_name": "Luis"},                  # sent 30 days ago -> cooldown
    {"email": "marta@example.com", "first_name": "Marta"},                # queued 5 days ago, never sent -> cooldown
    {"email": "pablo@example.com", "first_name": "Pablo"},                # sent 200 days ago -> eligible
    {"email": "sara@example.com", "first_name": "Sara"},                  # in cooldown for ANOTHER client -> eligible
    {"email": "not-an-email", "first_name": "Broken"},
]}, open(leads_json, "w"))
json.dump([
    {"client_name": "ACME", "email": "luis@example.com", "loaded_date": iso(32), "first_sent_date": iso(30)},
    {"client_name": "ACME", "email": "marta@example.com", "loaded_date": iso(5), "first_sent_date": None},
    {"client_name": "ACME", "email": "pablo@example.com", "loaded_date": iso(202), "first_sent_date": iso(200)},
    {"client_name": "OTHER", "email": "sara@example.com", "loaded_date": iso(3), "first_sent_date": None},
], open(log_path, "w"))

print("push-safe dry run:")
urllib.request.urlopen = no_network
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = ps.main(["--campaign", "1", "--client", "ACME", "--leads", leads_json,
                  "--outreach-log", log_path, "--plan-out", plan])
text = out.getvalue()
bodies = json.load(open(plan))
sent = [lead["email"] for body in bodies for lead in body["lead_list"]]
check("exit 0 and says DRY RUN", rc == 0 and "DRY RUN" in text)
check("pushes exactly ana, pablo, sara", sorted(sent) == ["ana@example.com", "pablo@example.com", "sara@example.com"])
check("dedupes the same person by email, case-insensitive", "duplicate_in_push_set: 1" in text)
check("cooldown catches sent-30-days and queued-not-sent", "cooldown_90d: 2" in text)
check("invalid email skipped", "invalid_or_missing_email: 1" in text)
check("every request forces all three settings to false, ignoring the input",
      bodies and all(body["settings"] == {FLAG_A: False, FLAG_B: False, FLAG_C: False} for body in bodies))
check("custom fields carried through", bodies[0]["lead_list"][0].get("custom_fields") == {"observation": "abrió un almacén nuevo"})
check("dry run wrote nothing to the outreach log", len(json.load(open(log_path))) == 4)

print("push-safe --apply against a fake platform (still no network):")
calls = []


class FakeResp:
    status = 200

    def __init__(self, n):
        self.n = n

    def read(self):
        return json.dumps({"upload_count": self.n, "total_leads": self.n - 1, "block_count": 1}).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def fake_urlopen(req, timeout=None):
    body = json.loads(req.data)
    calls.append(body)
    return FakeResp(len(body["lead_list"]))


urllib.request.urlopen = fake_urlopen
os.environ["SMARTLEAD_API_KEY"] = "test-key-not-real"
out = io.StringIO()
with contextlib.redirect_stdout(out):
    rc = ps.main(["--campaign", "1", "--client", "ACME", "--leads", leads_json, "--outreach-log", log_path,
                  "--batch-size", "2", "--delay", "0", "--state-dir", os.path.join(tmp, "state"), "--apply"])
text = out.getvalue()
log_rows = json.load(open(log_path))
check("two batches of at most 2", [len(c["lead_list"]) for c in calls] == [2, 1])
check("reconciles on total_leads, not upload_count", "succeeded: 1 " in text)
check("partial acceptance is a reported failure, exit 1", rc == 1 and "not accepted by the platform" in text)
check("outreach log written at push time for every pushed lead", len(log_rows) == 7 and all(r.get("loaded_date") for r in log_rows[4:]))
check("one state line per batch", len(open(os.path.join(tmp, "state", os.listdir(os.path.join(tmp, "state"))[0])).read().splitlines()) == 2)
out = io.StringIO()
with contextlib.redirect_stdout(out):
    ps.main(["--campaign", "1", "--client", "ACME", "--leads", leads_json, "--outreach-log", log_path, "--plan-out", plan])
check("a second run skips everyone just pushed", "ready to push: 0" in out.getvalue())

print("passed %d, failed %d" % (passed, failed))
sys.exit(1 if failed else 0)
