#!/usr/bin/env python3
"""Sending-capacity check: can the mailboxes on this campaign actually send what you loaded,
in the days you have? A run is not closed, and a campaign is not started, until this passes.

It is arithmetic on the numbers you give it. It proves the sum, not the inputs: read the lead
count, the number of sequence steps and the mailbox limits back from the platform before you
type them here.

    total sends needed   = leads x steps
    usable per day       = mailboxes x per-mailbox-per-day - other-load-per-day
    capacity in window   = usable per day x sending-days
    PASS when capacity in window >= total sends needed

On PASS it writes capacity-<campaign>.ok (JSON) into CAMPAIGN_STATE_DIR (default
.claude/campaign-state). The hardening hook refuses to start a campaign without a fresh one.
On FAIL it writes nothing, removes any older proof, and exits 1.

    python3 scripts/capacity-check.py --campaign 12345 --leads 400 --steps 3 \\
        --mailboxes 6 --per-mailbox-per-day 25 --sending-days 15
"""
import argparse
import datetime as dt
import json
import math
import os
import re
import sys


def verdict(leads, steps, mailboxes, per_mailbox_per_day, sending_days, other_load_per_day=0):
    """PURE. Returns (passed, numbers)."""
    needed = leads * steps
    usable = mailboxes * per_mailbox_per_day - other_load_per_day
    capacity = max(0, usable) * sending_days
    days_needed = math.ceil(needed / usable) if usable > 0 else None
    return capacity >= needed and needed > 0, {
        "total_sends_needed": needed, "usable_per_day": usable, "capacity_in_window": capacity,
        "sending_days_needed": days_needed}


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--campaign", required=True)
    p.add_argument("--leads", required=True, type=int, help="leads loaded in the campaign")
    p.add_argument("--steps", required=True, type=int, help="emails each lead receives if nobody replies")
    p.add_argument("--mailboxes", required=True, type=int, help="sending mailboxes attached to the campaign")
    p.add_argument("--per-mailbox-per-day", required=True, type=int, help="daily send limit of one mailbox")
    p.add_argument("--sending-days", required=True, type=int, help="sending days available before the sequence must be finished")
    p.add_argument("--other-load-per-day", type=int, default=0,
                   help="sends per day these same mailboxes already owe to other campaigns")
    p.add_argument("--state-dir", default=os.environ.get("CAMPAIGN_STATE_DIR") or os.path.join(".claude", "campaign-state"))
    args = p.parse_args(argv)
    if not re.match(r"^[A-Za-z0-9_-]+$", args.campaign):
        p.error("--campaign must be the literal campaign id")
    for name in ("leads", "steps", "mailboxes", "per_mailbox_per_day", "sending_days"):
        if getattr(args, name) < 1:
            p.error("--%s must be at least 1" % name.replace("_", "-"))
    if args.other_load_per_day < 0:
        p.error("--other-load-per-day cannot be negative")

    passed, numbers = verdict(args.leads, args.steps, args.mailboxes, args.per_mailbox_per_day,
                              args.sending_days, args.other_load_per_day)
    path = os.path.join(args.state_dir, "capacity-%s.ok" % args.campaign)
    print("campaign %s: %d sends needed, %d usable per day, %d capacity in %d sending days" % (
        args.campaign, numbers["total_sends_needed"], numbers["usable_per_day"], numbers["capacity_in_window"], args.sending_days))
    if not passed:
        try:
            os.remove(path)
        except OSError:
            pass
        need = numbers["sending_days_needed"]
        print("FAIL capacity: %s. Add mailboxes, cut the cohort, or give it more days. No proof written." % (
            "these mailboxes have nothing left per day" if need is None else "it needs %d sending days, you have %d" % (need, args.sending_days)),
            file=sys.stderr)
        return 1
    os.makedirs(args.state_dir, exist_ok=True)
    doc = {"campaign_id": str(args.campaign), "passed": True, "verified_at": dt.datetime.now(dt.timezone.utc).isoformat(),
           "inputs": {"leads": args.leads, "steps": args.steps, "mailboxes": args.mailboxes,
                      "per_mailbox_per_day": args.per_mailbox_per_day, "sending_days": args.sending_days,
                      "other_load_per_day": args.other_load_per_day},
           "numbers": numbers}
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(doc, fh, indent=1)
        fh.write("\n")
    print("PASS capacity: %s" % path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
