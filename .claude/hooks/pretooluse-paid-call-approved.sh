#!/usr/bin/env bash
# A paid provider call needs a spend approval from the run approval bundle: recorded, not
# expired, for THIS run, for THIS provider, inside its cap. Read-only commands never trip it.
# There is no bypass marker. The way through is the bundle, or the exceptions digest.
#   RUN_APPROVAL_SPEND=<run>:<provider>:<usd> <command>
exec python3 "$(dirname "$0")/_paid_call_guard.py"
