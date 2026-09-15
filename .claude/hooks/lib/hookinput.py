"""Shared stdin-JSON helpers for the campaign gate hooks.

Every hook receives the same JSON envelope on stdin from Claude Code:
  {"tool_name": "...", "tool_input": {...}}

These helpers pull out the fields the gates care about, without any
assumptions about which sending platform or database you use.
"""
import json
import sys


def load():
    """Read the hook envelope from stdin. Never raises - a malformed
    envelope must not brick the harness, so we fail open with an empty dict."""
    try:
        return json.loads(sys.stdin.read() or "{}")
    except Exception:
        return {}


def tool_name(payload):
    return payload.get("tool_name") or ""


def tool_input(payload):
    ti = payload.get("tool_input")
    return ti if isinstance(ti, dict) else {}


def command(payload):
    """The shell command, for Bash tool calls."""
    return tool_input(payload).get("command") or ""


def written_text(payload):
    """Everything a Write/Edit call would put on disk, concatenated."""
    ti = tool_input(payload)
    parts = [ti.get("content"), ti.get("new_string")]
    for edit in ti.get("edits") or []:
        if isinstance(edit, dict):
            parts.append(edit.get("new_string"))
    return "\n".join(p for p in parts if isinstance(p, str))


def file_path(payload):
    return tool_input(payload).get("file_path") or ""


def haystack(payload):
    """Command + written content. Most gates want to scan both."""
    return command(payload) + "\n" + written_text(payload)


def has_marker(payload, marker):
    """True if an operator bypass marker is present. Markers are deliberately
    verbose so they cannot appear by accident."""
    return marker in haystack(payload)


def block(message):
    """Refuse the tool call. Exit 2 is what Claude Code reads as 'blocked',
    and stderr is what it shows the model."""
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(2)


def allow():
    sys.exit(0)


def log(logfile, line):
    """Append one audit line. Best effort - never fail the hook over logging."""
    try:
        import datetime
        import os
        os.makedirs(os.path.dirname(logfile), exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(logfile, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {line}\n")
    except Exception:
        pass
