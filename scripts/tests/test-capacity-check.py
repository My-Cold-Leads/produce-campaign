#!/usr/bin/env python3
"""Prove scripts/capacity-check.py only writes a proof when the mailboxes can carry the load.

    python3 scripts/tests/test-capacity-check.py
"""
import contextlib
import importlib.util
import io
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
spec = importlib.util.spec_from_file_location("capacity_check", os.path.join(ROOT, "scripts", "capacity-check.py"))
cap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cap)

passed = failed = 0
tmp = tempfile.mkdtemp()
PROOF = os.path.join(tmp, "capacity-12345.ok")


def check(label, ok):
    global passed, failed
    print("  %s  %s" % ("ok  " if ok else "FAIL", label))
    passed, failed = passed + bool(ok), failed + (not ok)


def run(**numbers):
    args = {"leads": 400, "steps": 3, "mailboxes": 6, "per-mailbox-per-day": 25, "sending-days": 15}
    args.update({k.replace("_", "-"): v for k, v in numbers.items()})
    argv = ["--campaign", str(args.pop("campaign", "12345")), "--state-dir", tmp]
    for key, value in args.items():
        argv += ["--" + key, str(value)]
    out = io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
        try:
            rc = cap.main(argv)
        except SystemExit:
            rc = 99
    return rc, out.getvalue()


rc, text = run()
doc = json.load(open(PROOF)) if os.path.exists(PROOF) else {}
check("enough capacity passes and writes a proof naming the campaign",
      rc == 0 and doc.get("passed") is True and doc.get("campaign_id") == "12345" and doc.get("verified_at"))
rc, text = run(leads=4000)
check("RED: more sends than the mailboxes can carry fails", rc == 1 and "FAIL capacity" in text)
check("RED: a failed check removes the older proof", not os.path.exists(PROOF))
rc, text = run(sending_days=5)
check("RED: too few sending days fails and says how many it needs", rc == 1 and "needs 8 sending days" in text)
rc, text = run(other_load_per_day=150)
check("RED: mailboxes already full with other campaigns fail", rc == 1 and not os.path.exists(PROOF))
rc, text = run(other_load_per_day=60, sending_days=13)
check("RED: other load is taken off the daily capacity", rc == 1)
rc, text = run(other_load_per_day=60, sending_days=14)
check("the same load with enough days passes", rc == 0 and os.path.exists(PROOF))
for bad in ({"leads": 0}, {"mailboxes": 0}, {"steps": 0}, {"per_mailbox_per_day": 0}, {"sending_days": 0}, {"other_load_per_day": -1}):
    rc, text = run(**bad)
    check("RED: %s is refused" % bad, rc == 99)
rc, text = run(campaign="$CID")
check("RED: a campaign id that is not literal is refused", rc == 99)
check("the sum: 400 leads x 3 steps = 1200 sends, 6 x 25 = 150 a day, 8 days",
      cap.verdict(400, 3, 6, 25, 15)[1] == {"total_sends_needed": 1200, "usable_per_day": 150, "capacity_in_window": 2250, "sending_days_needed": 8})

print("passed %d, failed %d" % (passed, failed))
sys.exit(1 if failed else 0)
