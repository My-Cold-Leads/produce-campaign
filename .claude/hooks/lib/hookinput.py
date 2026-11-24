"""Shared stdin-JSON helpers for the campaign gate hooks.

Every hook receives the same JSON envelope on stdin from Claude Code:
  {"tool_name": "...", "tool_input": {...}}

What the hooks can see:
  Bash                  the command string
  Write/Edit/MultiEdit  the text being written and the file path
  MCP tools (mcp__*)    the tool name and its whole input, as JSON
Anything else (a tool your settings.json does not route here) is invisible to them.
"""
import json
import os
import re
import sys

MIN_REASON_CHARS = 10


def block(message):
    """Refuse the tool call. Exit 2 is what Claude Code reads as 'blocked',
    and stderr is what it shows the model."""
    sys.stderr.write(message.rstrip() + "\n")
    sys.exit(2)


def allow():
    sys.exit(0)


def load():
    """Read the hook envelope from stdin. FAILS CLOSED: an envelope this hook cannot parse
    is a tool call it cannot inspect, so it is blocked rather than waved through."""
    raw = sys.stdin.read()
    try:
        payload = json.loads(raw)
    except Exception:
        payload = None
    if not isinstance(payload, dict) or not isinstance(payload.get("tool_input", {}), dict):
        block("BLOCKED: this gate hook could not parse the tool call it was asked to inspect, "
              "so it cannot say the call is safe.\n"
              "Expected JSON on stdin: {\"tool_name\": ..., \"tool_input\": {...}}.\n"
              "If you are testing a hook by hand, build the payload with json.dumps.")
    return payload


def tool_name(payload):
    return payload.get("tool_name") or ""


def tool_input(payload):
    ti = payload.get("tool_input")
    return ti if isinstance(ti, dict) else {}


def is_mcp(payload):
    return tool_name(payload).startswith("mcp__")


def command(payload):
    """The shell command, for Bash tool calls."""
    value = tool_input(payload).get("command")
    return value if isinstance(value, str) else ""


def written_text(payload):
    """Everything a Write/Edit call would put on disk, concatenated."""
    ti = tool_input(payload)
    parts = [ti.get("content"), ti.get("new_string")]
    for edit in ti.get("edits") or []:
        if isinstance(edit, dict):
            parts.append(edit.get("new_string"))
    return "\n".join(p for p in parts if isinstance(p, str))


def file_path(payload):
    value = tool_input(payload).get("file_path")
    return value if isinstance(value, str) else ""


def mcp_text(payload):
    """Tool name plus full input for an MCP call, so the same patterns that catch a curl
    command also catch the equivalent tool call."""
    if not is_mcp(payload):
        return ""
    return tool_name(payload) + "\n" + json.dumps(tool_input(payload), ensure_ascii=False)


def haystack(payload):
    """Command + written content + MCP call. Most gates scan all three."""
    return command(payload) + "\n" + written_text(payload) + "\n" + mcp_text(payload)


def bypass(payload, marker, logfile, detail=""):
    """True when an operator bypass marker with a written reason is present.

    A marker is an audit trail, not a control: whoever can type the command can type the
    marker. So it must carry a reason, the reason is logged with the tool and time, and
    setting CAMPAIGN_HOOKS_NO_BYPASS=1 switches every marker off.
    """
    hay = haystack(payload)
    if marker not in hay:
        return False
    if os.environ.get("CAMPAIGN_HOOKS_NO_BYPASS") == "1":
        block("BLOCKED: bypass markers are switched off here (CAMPAIGN_HOOKS_NO_BYPASS=1). "
              "Fix the cause instead.")
    found = re.search(re.escape(marker) + r"[ \t]*([^\n\"']*)", hay)
    reason = (found.group(1) if found else "").strip()
    if len(reason) < MIN_REASON_CHARS:
        block("BLOCKED: bypass marker %s needs a reason on the same line (at least %d characters) "
              "saying why and who approved it. The reason is written to the audit log."
              % (marker, MIN_REASON_CHARS))
    log(logfile, "BYPASS marker=%s tool=%s %s reason=%s" % (marker, tool_name(payload), detail, reason[:300]))
    return True


def log_path(name):
    """Audit logs live in .claude/ unless CAMPAIGN_HOOK_LOG_DIR says otherwise."""
    base = os.environ.get("CAMPAIGN_HOOK_LOG_DIR") or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "..", "..")
    return os.path.join(base, name)


def log(logfile, line):
    """Append one audit line. If the line cannot be written the bypass is refused:
    an unlogged bypass is the thing this file exists to prevent."""
    try:
        import datetime
        os.makedirs(os.path.dirname(os.path.abspath(logfile)), exist_ok=True)
        stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        with open(logfile, "a", encoding="utf-8") as fh:
            fh.write(f"{stamp} {line}\n")
    except Exception as exc:
        block("BLOCKED: could not write the bypass audit log (%s), so the bypass is refused." % type(exc).__name__)
