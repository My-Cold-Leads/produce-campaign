import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import hookinput as H  # noqa: E402

MARKER = "PUSH_SAFE_OK:"
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "push-safe-bypass.log")

# The wrapper this repo ships is scripts/push-safe.py. Set PUSH_SAFE_WRAPPER to
# the base name of your own wrapper if you renamed it.
WRAPPER = os.environ.get("PUSH_SAFE_WRAPPER", "push-safe")

# Flags that switch off the platform's own suppression lists. There is no
# legitimate value other than false.
SUPPRESSION_OFF = re.compile(
    r"""["']?(ignore_global_block_list|ignore_unsubscribe_list)["']?\s*[:=]\s*["']?true""",
    re.I,
)

# A raw lead push straight at the API, bypassing the wrapper.
RAW_PUSH = re.compile(
    r"""(POST|--request\s+POST|-X\s*POST|method:\s*["']POST["'])""" r"""[\s\S]{0,400}?/campaigns/[^/\s"']+/leads""",
    re.I,
)
RAW_PUSH_ALT = re.compile(r"""/campaigns/[^/\s"']+/leads[\s\S]{0,200}?(POST|-X\s*POST)""", re.I)


def is_wrapper_source(payload):
    """True when a Write/Edit targets the wrapper's own source file. The wrapper
    is the one place allowed to contain the raw endpoint - that is its job."""
    base = os.path.basename(H.file_path(payload))
    return bool(base) and os.path.splitext(base)[0] == WRAPPER


def main():
    payload = H.load()
    hay = H.haystack(payload)
    if not hay.strip():
        H.allow()

    bypassed = H.has_marker(payload, MARKER)

    if SUPPRESSION_OFF.search(hay):
        # This one is NEVER bypassable. It does not even work: the platform
        # runs its own enforcement pass afterwards and strips the leads back
        # out, after some of them have already been emailed.
        H.block(
            "BLOCKED: this push switches off the sending platform's suppression list.\n\n"
            "  ignore_global_block_list / ignore_unsubscribe_list must be false. Always.\n\n"
            "The block list is how bounce history and unsubscribe requests are enforced.\n"
            "Bypassing it at import time is silent damage: we pushed a few hundred leads this\n"
            "way; the platform accepted them, then stripped about two thirds within 24 hours.\n\n"
            "The real fix is upstream: get the address removed from the block list\n"
            "properly, or mark it do-not-contact on your side and stop pushing it.\n\n"
            "There is no bypass marker for this rule."
        )

    # Running the wrapper from the shell never contains the raw endpoint, so it
    # passes the check below on its own. Editing the wrapper's source does
    # contain it, and is allowed by name.
    if is_wrapper_source(payload):
        H.allow()

    if RAW_PUSH.search(hay) or RAW_PUSH_ALT.search(hay):
        if bypassed:
            H.log(LOG, f"BYPASS raw-push tool={H.tool_name(payload)}")
            H.allow()
        H.block(
            "BLOCKED: raw lead push detected. Route it through your push wrapper:\n"
            f"  python3 scripts/{WRAPPER}.py --campaign <id> --client <name> --leads leads.csv\n"
            "  (dry run by default; add --apply after the push approval gate)\n\n"
            "The wrapper is where three things happen that the raw endpoint does not do:\n"
            "  1. The cooldown gate - do not re-contact someone you mailed recently.\n"
            "  2. Cross-campaign dedup against your OWN send history. The platform's\n"
            "     own duplicate check is blind to whether anything was ever sent, and\n"
            "     over-blocks; it silently rejected over half of one push, and a sample\n"
            "     showed only about 2% were genuine cooldowns.\n"
            "  3. Outreach logging AT PUSH TIME, so the cooldown works on the next run.\n"
            "     Log it later and queued-but-unsent leads look free to push again.\n\n"
            f"Emergency one-off: add  {MARKER} <reason>  to the command (logged).\n"
            "Using that for a production load is a bug in the caller - fix the caller."
        )

    H.allow()


main()
