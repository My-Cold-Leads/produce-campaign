#!/usr/bin/env bash
# Custom fields are PLAIN DATA. Spintax and platform variables inside them do
# not resolve - they ship literally, into a real inbox.
# Bypass: CUSTOM_FIELD_OK: <reason>
exec python3 "$(dirname "$0")/_custom_field_guard.py"
