import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import hookinput as H  # noqa: E402

MARKER = "DURABLE_WRITES_OK:"
LOG = H.log_path("durable-writes-bypass.log")

# Endpoints that bill per call. Extend for your own vendors.
SPEND = re.compile(
    "|".join([r"api\.anthropic\.com", r"api\.openai\.com", r"/v1/enrich", r"/v1/search",
              r"serper\.dev", r"\.people\.match", r"bulk_match"]),
    re.I,
)
LOOP = re.compile(r"^\s*(for|while)\s", re.M)
ACCUMULATE = re.compile(r"^\s*\w+\.append\(|^\s*\w+\.push\(", re.M)
PERSIST = re.compile(r"(INSERT\s+INTO|\.upsert\(|\.insert\(|writeFileSync|\.to_csv\(|json\.dump)", re.I)


def main():
    payload = H.load()
    text = H.written_text(payload) + "\n" + H.command(payload)
    if not text.strip():
        H.allow()
    if not (SPEND.search(text) and LOOP.search(text) and PERSIST.search(text) and ACCUMULATE.search(text)):
        H.allow()

    # Conservative positional heuristic: if every persistence call sits after the
    # last in-loop accumulation, the results are being buffered to the end.
    last_append = max((m.end() for m in ACCUMULATE.finditer(text)), default=0)
    if not all(m.start() > last_append for m in PERSIST.finditer(text)):
        H.allow()

    if H.bypass(payload, MARKER, LOG):
        H.allow()

    H.block(
        "BLOCKED: this loop spends money per record and writes only at the end.\n\n"
        "Everything in that list is paid for. If the final write fails, or the process\n"
        "is killed, or one row is rejected, you have bought all of it and kept none.\n"
        "A three-hour run held thousands of finished results in memory, wrote at the\n"
        "very end, and lost about 40% of them to a single rejected request.\n\n"
        "Instead:\n"
        "  - write each record as soon as it exists, inside the loop\n"
        "  - wrap each row so one bad row costs one row, never the rest of the run\n"
        "  - report attempted / succeeded / failed with the failing identifiers\n"
        "  - read the error body; a bare '409: Conflict' with the response discarded is\n"
        "    undiagnosable an hour later\n\n"
        "A human operator can authorise a one-off; see README, 'Bypass markers'."
    )


main()
