import datetime
import json
import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import hookinput as H  # noqa: E402

MARKER = "HARDENING_OK:"
HOOKS = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("CAMPAIGN_STATE_DIR") or os.path.join(HOOKS, "..", "campaign-state")
LOG = H.log_path("hardening-bypass.log")
MAX_AGE_MIN = int(os.environ.get("HARDENING_MAX_AGE_MIN", "120"))
CAPACITY_MAX_AGE_MIN = int(os.environ.get("CAPACITY_MAX_AGE_MIN", "1440"))
REQUIRED_CHECKS = ("open_tracking_off", "click_tracking_off", "plain_text_on")

# Actions that put mail on the wire: starting a campaign, or loading leads into one
# (a finished campaign restarts by itself when leads land).
STATUS_TOUCH = re.compile(r"(update_campaign_status|/campaigns/[^/\s\"']+/status)", re.I)
STATUS_START = re.compile(r"""["']?status["']?\s*[:=]\s*["']?(START|ACTIVE)\b""", re.I)
STATUS_HALT = re.compile(r"""["']?status["']?\s*[:=]\s*["']?(PAUSED?|STOP(PED)?)\b""", re.I)
LEAD_LOAD = re.compile(
    r"(add_leads_to_campaign|push_leads_to_campaign|/campaigns/[^/\s\"']+/leads|push-safe\S*\s[^\n]*--apply)", re.I)
ID_PATTERNS = (
    re.compile(r"--campaign(?:-id)?[=\s]+[\"']?([A-Za-z0-9_-]+)"),
    re.compile(r"/campaigns/([A-Za-z0-9_-]+)/(?:status|leads)"),
    re.compile(r"(?:add_leads_to_campaign|push_leads_to_campaign|update_campaign_status)[\s(\"']+([0-9]+)"),
    re.compile(r"""["']?campaign_?[iI]d["']?\s*[:=]\s*["']?([A-Za-z0-9_-]+)"""),
)


def sends(hay):
    if LEAD_LOAD.search(hay) or STATUS_START.search(hay):
        return True
    # Pausing or stopping is the safety action and never needs a proof.
    return bool(STATUS_TOUCH.search(hay)) and not STATUS_HALT.search(hay)


def starts(hay):
    """True for a go-live (status START), as opposed to a lead load."""
    if STATUS_START.search(hay):
        return True
    return bool(STATUS_TOUCH.search(hay)) and not STATUS_HALT.search(hay)


def capacity_problem(campaign_id):
    """Why this campaign has no usable sending-capacity proof, or None. Written by
    scripts/capacity-check.py; one campaign per proof, and it goes stale."""
    path = os.path.join(STATE, "capacity-%s.ok" % campaign_id)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
    except OSError:
        return "capacity: no capacity proof for this campaign"
    except ValueError:
        return "capacity: the proof file is not the JSON written by scripts/capacity-check.py"
    if not isinstance(doc, dict) or str(doc.get("campaign_id")) != str(campaign_id):
        return "capacity: the proof names a different campaign"
    if doc.get("passed") is not True:
        return "capacity: the proof does not show a pass"
    try:
        when = datetime.datetime.fromisoformat(str(doc.get("verified_at")).replace("Z", "+00:00"))
        age = (datetime.datetime.now(datetime.timezone.utc) - when).total_seconds() / 60.0
    except (ValueError, TypeError):
        return "capacity: the proof has no verified_at time"
    if age > CAPACITY_MAX_AGE_MIN or age < -5:
        return "capacity: the proof is older than %d minutes" % CAPACITY_MAX_AGE_MIN
    return None


def campaign_ids(payload, hay):
    ids = set()
    if H.is_mcp(payload):
        ti = H.tool_input(payload)
        for key in ("campaign_id", "campaignId", "campaign"):
            if isinstance(ti.get(key), (str, int)) and str(ti[key]).strip():
                ids.add(str(ti[key]).strip())
    for pattern in ID_PATTERNS:
        ids.update(pattern.findall(hay))
    return sorted(ids)


def proof_problem(campaign_id):
    """Why this campaign has no usable proof, or None when it does.

    A proof unlocks ONLY the campaign it names. It must be the JSON that
    scripts/verify-hardening.py writes after reading the campaign back from the platform:
    an empty file made with touch says nothing about any setting and is not accepted.
    """
    path = os.path.join(STATE, "hardening-%s.ok" % campaign_id)
    try:
        with open(path, encoding="utf-8") as fh:
            doc = json.load(fh)
        age_file = (time.time() - os.path.getmtime(path)) / 60.0
    except OSError:
        return "no proof file for this campaign"
    except ValueError:
        return "the proof file is not the JSON written by scripts/verify-hardening.py"
    if not isinstance(doc, dict) or str(doc.get("campaign_id")) != str(campaign_id):
        return "the proof file names a different campaign"
    checks = doc.get("checks") if isinstance(doc.get("checks"), dict) else {}
    missing = [c for c in REQUIRED_CHECKS if checks.get(c) is not True]
    if missing:
        return "the proof does not show: " + ", ".join(missing)
    try:
        when = datetime.datetime.fromisoformat(str(doc.get("verified_at")).replace("Z", "+00:00"))
        age_doc = (datetime.datetime.now(datetime.timezone.utc) - when).total_seconds() / 60.0
    except (ValueError, TypeError):
        return "the proof has no verified_at time"
    if max(age_file, age_doc) > MAX_AGE_MIN or age_doc < -5:
        return "the proof is older than %d minutes" % MAX_AGE_MIN
    return None


def main():
    payload = H.load()
    hay = H.haystack(payload)
    if not hay.strip() or not sends(hay):
        H.allow()

    ids = campaign_ids(payload, hay)
    if H.bypass(payload, MARKER, LOG, detail="campaigns=%s" % ",".join(ids)):
        H.allow()

    if not ids:
        H.block(
            "BLOCKED: this looks like a send (campaign start or lead load) but the campaign id is not\n"
            "readable from the call, so the hardening proof cannot be matched to a campaign.\n"
            "Write the id literally (for example --campaign 12345, not a shell variable)."
        )
    problems = [(cid, proof_problem(cid)) for cid in ids]
    if starts(hay):
        # Going live also needs the sending-capacity check. Loading leads into a draft does not.
        problems += [(cid, capacity_problem(cid)) for cid in ids]
    problems = [(cid, why) for cid, why in problems if why]
    if not problems:
        H.allow()
    if all(why.startswith("capacity:") for _, why in problems):
        H.block(
            "BLOCKED: about to put a campaign live with no sending-capacity proof for:\n"
            + "".join("  campaign %s: %s\n" % (cid, why) for cid, why in problems)
            + "\nA run is not closed, and a campaign is not started, until the capacity check passes:\n"
            "    python3 scripts/capacity-check.py --campaign <campaign_id> --leads <n> --steps <n> \\\n"
            "        --mailboxes <n> --per-mailbox-per-day <n> --sending-days <n>\n"
            "Read the lead count, the steps and the mailbox limits back from the platform first.\n"
            f"The proof goes stale after {CAPACITY_MAX_AGE_MIN} minutes."
        )

    H.block(
        "BLOCKED: about to send, with no fresh hardening proof for:\n"
        + "".join("  campaign %s: %s\n" % (cid, why) for cid, why in problems)
        + "\nA proof for one campaign never unlocks another.\n\n"
        "Settings that decide whether your email looks like mail or like marketing:\n"
        "  open tracking   OFF   (the pixel is a spam signal and tells you nothing useful)\n"
        "  click tracking  OFF   (rewritten links on a new domain are a strong spam signal)\n"
        "  plain text      ON    (HTML multipart from a cold domain underperforms)\n\n"
        "Two traps:\n"
        "  1. Tracking cannot be changed once the campaign starts sending, so verify at draft time.\n"
        "  2. Saving any other campaign setting can silently reset plain text to off.\n\n"
        "Read the campaign back and record the proof (read-only, writes the proof file on success):\n"
        "    python3 scripts/verify-hardening.py --campaign <campaign_id>\n\n"
        f"Proof goes stale after {MAX_AGE_MIN} minutes on purpose. Re-verify immediately before\n"
        "launch and after every settings change.\n"
        "A human operator can authorise a one-off; see README, 'Bypass markers'."
    )


main()
