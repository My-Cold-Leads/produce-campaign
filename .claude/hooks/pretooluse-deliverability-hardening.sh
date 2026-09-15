#!/usr/bin/env bash
# Refuses to send until tracking is off and plain text is on, VERIFIED by a
# live read of the campaign rather than by remembering that you set it.
# Bypass: HARDENING_OK: <reason>
exec python3 "$(dirname "$0")/_hardening_guard.py"
