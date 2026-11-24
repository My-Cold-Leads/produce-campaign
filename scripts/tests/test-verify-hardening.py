#!/usr/bin/env python3
"""Prove scripts/verify-hardening.py only writes a proof for a campaign that reads back hardened.
No network: the platform is a fake.

    python3 scripts/tests/test-verify-hardening.py
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location("verify_hardening", os.path.join(ROOT, "scripts", "verify-hardening.py"))
vh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vh)

passed = failed = 0
GOOD = {"id": 12345, "name": "ACME E1", "track_settings": ["DONT_EMAIL_OPEN", "DONT_LINK_CLICK"],
        "send_as_plain_text": True, "min_time_btwn_emails": 5, "follow_up_percentage": 50}
live = {}


class FakeResp:
    def read(self):
        return json.dumps(live).encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


urllib.request.urlopen = lambda req, timeout=None: FakeResp()
os.environ["SMARTLEAD_API_KEY"] = "test-key-not-real"
state = tempfile.mkdtemp()
proof = os.path.join(state, "hardening-12345.ok")


def check(label, ok):
    global passed, failed
    print("  %s  %s" % ("ok  " if ok else "FAIL", label))
    passed, failed = passed + bool(ok), failed + (not ok)


def run(doc, *extra):
    live.clear()
    live.update(doc)
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        rc = vh.main(["--campaign", "12345", "--state-dir", state, *extra])
    return rc, out.getvalue()


rc, text = run(GOOD, "--follow-up-percent", "50")
doc = json.load(open(proof)) if os.path.exists(proof) else {}
check("hardened campaign passes and writes a proof naming the campaign",
      rc == 0 and doc.get("campaign_id") == "12345" and all(doc["checks"].values()) and doc.get("verified_at"))
for label, bad, extra in (
    ("RED: open tracking on", dict(GOOD, track_settings=["DONT_LINK_CLICK"]), ()),
    ("RED: click tracking on", dict(GOOD, track_settings=["DONT_EMAIL_OPEN"]), ()),
    ("RED: tracking settings empty", dict(GOOD, track_settings=[]), ()),
    ("RED: plain text off", dict(GOOD, send_as_plain_text=False), ()),
    ("RED: plain text missing from the response", {k: v for k, v in GOOD.items() if k != "send_as_plain_text"}, ()),
    ("RED: a campaign-level gap is set", dict(GOOD, min_time_btwn_emails=20), ()),
    ("RED: follow-up percentage is not the agreed value", dict(GOOD, follow_up_percentage=100), ("--follow-up-percent", "50")),
    ("RED: the platform returns no campaign", {}, ()),
):
    run(GOOD)
    rc, text = run(bad, *extra)
    check(label + " -> exit 1 and the old proof is removed", rc == 1 and not os.path.exists(proof))
rc, text = run(GOOD)
check("without --follow-up-percent it says that check did not run", rc == 0 and "NOT checked" in text)

print("passed %d, failed %d" % (passed, failed))
sys.exit(1 if failed else 0)
