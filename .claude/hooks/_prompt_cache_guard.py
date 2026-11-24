import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import hookinput as H  # noqa: E402

MARKER = "CACHE_OK:"
LOG = H.log_path("prompt-cache-bypass.log")
# Which endpoints count as a cacheable LLM call. Override LLM_ENDPOINT_RE to add
# your own provider, or to point the falsifiability test at a fixture host.
DEFAULT_ENDPOINTS = r"api\.anthropic\.com/v1/messages"
ENDPOINT = re.compile(os.environ.get("LLM_ENDPOINT_RE", DEFAULT_ENDPOINTS), re.I)
LOOPY = re.compile(r"^\s*(for|while)\s|\.map\(|\.forEach\(|ThreadPool|asyncio\.gather", re.M)
CACHED = re.compile(r"cache_control", re.I)


def main():
    payload = H.load()
    text = H.written_text(payload) + "\n" + H.command(payload)
    if not text.strip() or not ENDPOINT.search(text) or not LOOPY.search(text) or CACHED.search(text):
        H.allow()
    if H.bypass(payload, MARKER, LOG):
        H.allow()
    H.block(
        "BLOCKED: a loop of LLM calls with no cache_control on the system block.\n\n"
        "Every iteration re-sends and re-pays for the same system prompt. On a\n"
        "thousand-record run that is most of the bill, for identical output.\n\n"
        "Two things make it work, and you need both:\n"
        "  1. cache_control {\"type\": \"ephemeral\"} on the last static system block\n"
        "  2. a byte-identical prefix across every call - put per-record data at the\n"
        "     END under '## VARIABLES:'. One stray timestamp or record id near the top\n"
        "     silently voids the cache for the whole run.\n\n"
        "Wrap your caller in one function that always sets this, rather than trusting\n"
        "each script to remember.\n\n"
        "A human operator can authorise a one-off; see README, 'Bypass markers'."
    )


main()
