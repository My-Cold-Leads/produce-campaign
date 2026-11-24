#!/usr/bin/env python3
"""Read a Smartlead campaign back from the API and prove it is safe to send from.

Read-only against the platform. On success it writes the proof file the deliverability hook
looks for (.claude/campaign-state/hardening-<campaign_id>.ok). On any failure it writes
nothing, removes a stale proof for that campaign, and exits 1.

Checks:
  open tracking OFF, click tracking OFF     track_settings holds DONT_EMAIL_OPEN and DONT_LINK_CLICK
  plain text ON                             send_as_plain_text is true
  no campaign-level gap                     min_time_btwn_emails is at the platform floor (5 minutes
                                            or less). The gap between emails belongs on each inbox,
                                            never on the campaign: a campaign gap overrides every inbox
                                            and quietly cuts volume.
  follow-up percentage (optional)           --follow-up-percent N must equal the live value. Agree it
                                            per client and per number of emails in the sequence; the
                                            platform default is rarely what you want.

    SMARTLEAD_API_KEY=... python3 scripts/verify-hardening.py --campaign 12345 --follow-up-percent 50

Run it while the campaign is a draft, after every settings change, and immediately before launch.
Python 3 standard library only.
"""
import argparse
import datetime as dt
import json
import os
import sys
import urllib.error
import urllib.request

API_BASE = "https://server.smartlead.ai/api/v1"
CAMPAIGN_GAP_FLOOR_MIN = 5
DEFAULT_STATE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".claude", "campaign-state")


def fetch_campaign(campaign, api_key, timeout=30):
    """Returns (campaign dict, None) or (None, error). The URL holds the key and is never printed."""
    req = urllib.request.Request("%s/campaigns/%s?api_key=%s" % (API_BASE, campaign, api_key), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            doc = json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        return None, "HTTP %s" % exc.code
    except Exception as exc:
        return None, type(exc).__name__
    if not isinstance(doc, dict) or doc.get("id") is None:
        return None, "no campaign returned for this id"
    return doc, None


def evaluate(doc, follow_up_percent=None):
    """Returns (checks, failures). checks is what goes into the proof file."""
    track = doc.get("track_settings")
    if isinstance(track, str):
        try:
            track = json.loads(track)
        except ValueError:
            track = [track]
    track = [str(x).upper() for x in (track or [])]
    gap = doc.get("min_time_btwn_emails")
    checks = {
        "open_tracking_off": "DONT_EMAIL_OPEN" in track,
        "click_tracking_off": "DONT_LINK_CLICK" in track,
        "plain_text_on": doc.get("send_as_plain_text") is True,
        "no_campaign_level_gap": gap is None or (isinstance(gap, (int, float)) and gap <= CAMPAIGN_GAP_FLOOR_MIN),
    }
    failures = [name for name, ok in checks.items() if not ok]
    if follow_up_percent is not None:
        checks["follow_up_percent_matches"] = doc.get("follow_up_percentage") == follow_up_percent
        if not checks["follow_up_percent_matches"]:
            failures.append("follow_up_percent_matches (live %r, agreed %r)" % (doc.get("follow_up_percentage"), follow_up_percent))
    return checks, failures


def main(argv=None):
    p = argparse.ArgumentParser(description="Verify campaign hardening by reading it back. Read-only.")
    p.add_argument("--campaign", required=True)
    p.add_argument("--follow-up-percent", type=int, help="the agreed follow-up percentage for this client and sequence length")
    p.add_argument("--state-dir", default=os.environ.get("CAMPAIGN_STATE_DIR") or DEFAULT_STATE)
    args = p.parse_args(argv)
    api_key = os.environ.get("SMARTLEAD_API_KEY", "")
    if not api_key:
        p.error("SMARTLEAD_API_KEY is not set")
    proof = os.path.join(args.state_dir, "hardening-%s.ok" % args.campaign)

    doc, error = fetch_campaign(args.campaign, api_key)
    checks, failures = evaluate(doc, args.follow_up_percent) if doc else ({}, ["could not read the campaign (%s)" % error])
    if failures:
        if os.path.exists(proof):
            os.remove(proof)
        print("NOT HARDENED - campaign %s" % args.campaign, file=sys.stderr)
        for f in failures:
            print("  failed: %s" % f, file=sys.stderr)
        print("Fix the settings (tracking first, then plain text), then run this again. No proof written.", file=sys.stderr)
        return 1
    os.makedirs(args.state_dir, exist_ok=True)
    with open(proof, "w", encoding="utf-8") as fh:
        json.dump({"campaign_id": str(args.campaign), "campaign_name": doc.get("name"), "checks": checks,
                   "verified_at": dt.datetime.now(dt.timezone.utc).isoformat()}, fh, indent=1)
    print("HARDENED - campaign %s (%s)" % (args.campaign, ", ".join(sorted(checks))))
    if args.follow_up_percent is None:
        print("note: follow-up percentage NOT checked (pass --follow-up-percent to check it)")
    print("proof: %s" % proof)
    return 0


if __name__ == "__main__":
    sys.exit(main())
