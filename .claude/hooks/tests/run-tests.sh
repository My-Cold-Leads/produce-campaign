#!/usr/bin/env bash
# Falsifiability harness for the campaign gates.
#
# Every gate must BLOCK a known-bad input and ALLOW a known-good one. A gate that
# has never gone red might be working, or might be silently no-opping - this is
# how you tell the difference. Build the failing input BEFORE you trust the green.
#
# Everything below is an inert fixture string piped into a hook on stdin. No
# request is made, no model is called, nothing is spent.
#
#   bash .claude/hooks/tests/run-tests.sh
cd "$(dirname "$0")/.." || exit 1
exec python3 tests/run_tests.py
