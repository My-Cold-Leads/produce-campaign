#!/usr/bin/env bash
# A loop of LLM calls sharing a system prompt must cache it. Uncached loops cost
# several times more for identical output.
# Bypass: CACHE_OK: <reason of 10+ characters> (logged with the reason; see README)
exec python3 "$(dirname "$0")/_prompt_cache_guard.py"
