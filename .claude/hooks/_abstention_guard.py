import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import hookinput as H  # noqa: E402

MARKER = "ABSTENTION_OK:"
LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "abstention-bypass.log")
TOKEN = os.environ.get("ABSTENTION_TOKEN", "NOT_FOUND")
PUSH_INTENT = re.compile(r"(/campaigns/[^/\s\"']+/leads|add_leads|push_leads|update_lead)", re.I)
# custom_fields on its own is just a word - grepping a results file mentions it.
# It only counts as a push when a sending verb is in the same payload.
CUSTOM_FIELDS = re.compile(r"custom_fields", re.I)
SEND_VERB = re.compile(r"(\bPOST\b|\.post\(|\bpush\b|\bupload\b|\bsend\b|push-safe|--apply)", re.I)


def main():
    payload = H.load()
    hay = H.haystack(payload)
    push = PUSH_INTENT.search(hay) or (CUSTOM_FIELDS.search(hay) and SEND_VERB.search(hay))
    if not hay.strip() or not push or TOKEN not in hay:
        H.allow()
    if H.has_marker(payload, MARKER):
        H.log(LOG, f"BYPASS tool={H.tool_name(payload)}")
        H.allow()
    H.block(
        f"BLOCKED: the abstention token {TOKEN} is in a payload headed for a lead.\n\n"
        f"{TOKEN} means the model correctly refused to invent something the source did\n"
        "not support. That is the system working. But it is a signal for your code, not\n"
        "copy - if it reaches a send, the lead reads it.\n\n"
        "Store it as NULL, check for NULL in the consumer, and drop to the next opener\n"
        "tier, ending at the sourced floor (what they make + where, then the question).\n"
        "Never ship a claim the source does not support. Then grep the final push payload\n"
        "for the token as a last check - which is what just happened.\n\n"
        f"Bypass: {MARKER} <reason>  (logged)"
    )


main()
