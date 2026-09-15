#!/usr/bin/env bash
# Paid work is persisted the moment it exists, not buffered and flushed at the end.
# Bypass: DURABLE_WRITES_OK: <reason>
exec python3 "$(dirname "$0")/_durable_writes_guard.py"
