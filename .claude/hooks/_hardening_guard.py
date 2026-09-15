import os
import re
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import hookinput as H  # noqa: E402

MARKER = "HARDENING_OK:"
HOOKS = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HOOKS, "..", "campaign-state")
LOG = os.path.join(HOOKS, "..", "hardening-bypass.log")
MAX_AGE_MIN = int(os.environ.get("HARDENING_MAX_AGE_MIN", "120"))

# Actions that put mail on the wire.
SEND_INTENT = re.compile(
    r"(update_campaign_status|/campaigns/[^/\s\"']+/status|"
    r"""["']?status["']?\s*[:=]\s*["']?(START|ACTIVE)\b|add_leads_to_campaign|push_leads_to_campaign|"""
    r"/campaigns/[^/\s\"']+/leads|"
    r"push-safe\S*\s[^\n]*--apply)",
    re.I,
)


def fresh_proof():
    """A hardening proof file is written by your verification script after it
    reads the campaign back from the API. Returns the campaign ids proven."""
    try:
        names = os.listdir(STATE)
    except OSError:
        return []
    proven = []
    now = time.time()
    for n in names:
        if not n.startswith("hardening-") or not n.endswith(".ok"):
            continue
        p = os.path.join(STATE, n)
        try:
            if (now - os.path.getmtime(p)) / 60.0 <= MAX_AGE_MIN:
                proven.append(n[len("hardening-"):-len(".ok")])
        except OSError:
            continue
    return proven


def main():
    payload = H.load()
    hay = H.haystack(payload)
    if not hay.strip() or not SEND_INTENT.search(hay):
        H.allow()

    if H.has_marker(payload, MARKER):
        H.log(LOG, f"BYPASS tool={H.tool_name(payload)}")
        H.allow()

    if fresh_proof():
        H.allow()

    H.block(
        "BLOCKED: about to send, with no fresh proof that the campaign is hardened.\n\n"
        "Two settings decide whether your email looks like mail or like marketing:\n"
        "  open tracking   OFF   (the pixel is a spam signal and tells you nothing useful)\n"
        "  click tracking  OFF   (rewritten links on a new domain are a strong spam signal)\n"
        "  plain text      ON    (HTML multipart from a cold domain underperforms)\n\n"
        "Two traps, both of which have bitten us:\n"
        "  1. Tracking is immutable once the campaign starts sending. Get it wrong and\n"
        "     you rebuild the campaign - so this is verified at DRAFT time, not after.\n"
        "  2. Saving any other campaign setting silently resets plain text to off.\n"
        "     Renaming a campaign un-hardens it, with no error and no warning.\n"
        "     An audit found roughly a third of our campaigns un-hardened, mostly from this.\n\n"
        "So: READ the campaign back from the API, assert the exact expected values,\n"
        "then record the proof:\n"
        f"    mkdir -p {os.path.normpath(STATE)}\n"
        f"    touch {os.path.normpath(STATE)}/hardening-<campaign_id>.ok\n\n"
        f"Proof goes stale after {MAX_AGE_MIN} minutes, on purpose - re-verify\n"
        "immediately before launch and after every settings change.\n\n"
        f"Bypass: {MARKER} <reason>  (logged)"
    )


main()
