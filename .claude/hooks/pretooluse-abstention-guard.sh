#!/usr/bin/env bash
# The model may say "I don't know" by returning the abstention token. That token
# is a signal for your code, never something a lead reads.
# Bypass: ABSTENTION_OK: <reason>
exec python3 "$(dirname "$0")/_abstention_guard.py"
