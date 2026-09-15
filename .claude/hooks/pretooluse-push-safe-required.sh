#!/usr/bin/env bash
# Blocks two things that have each cost real campaigns real damage:
#   1. Turning OFF the sending platform's own suppression lists.
#   2. Pushing leads by hand instead of through your wrapper, which is
#      where your dedup, cooldown and outreach logging live.
# See CLAUDE.md "Never Switch Off the Block List".
# Bypass (logged, and a bug in the caller if you use it in production):
#   PUSH_SAFE_OK: <reason>
exec python3 "$(dirname "$0")/_push_safe_guard.py"
