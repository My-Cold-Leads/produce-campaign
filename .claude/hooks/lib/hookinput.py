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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import statements as S  # noqa: E402

MIN_REASON_CHARS = 10
CAMPAIGN_KEYS = ("campaign_id", "campaignId", "campaign")


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


def active_command(payload):
    """The parts of a Bash command that can act. Read-only statements (grep, cat, sed -n,
    git show, bash -n ...) and heredoc bodies that are only written to a file are left out, so
    a gate never blocks someone for reading. See lib/statements.py."""
    return S.active_text(command(payload))


def command_segments(payload):
    return S.segments(command(payload))


def haystack(payload):
    """Acting command statements + written content + MCP call. Most gates scan all three."""
    return active_command(payload) + "\n" + written_text(payload) + "\n" + mcp_text(payload)


def mcp_campaign(payload):
    ti = tool_input(payload)
    for key in CAMPAIGN_KEYS:
        value = ti.get(key)
        if isinstance(value, (str, int)) and not isinstance(value, bool) and str(value).strip():
            return str(value).strip()
    return ""


def marker_reason(payload, marker):
    """The reason carried by a REAL bypass marker, or None when there is no real marker.

    Bash        a trailing shell comment on the last line:   <command>  # MARKER: reason
                (the marker inside a quoted string, an echo, or a heredoc is not a marker)
    Write/Edit  a comment line of its own in the written text:  # MARKER: reason
    MCP         an input field named after the marker in lower case (PUSH_SAFE_OK: -> push_safe_ok)
                whose value is "campaign=<id>; reason", where <id> is the campaign the call names
    """
    if is_mcp(payload):
        value = tool_input(payload).get(marker.rstrip(":").lower())
        if not isinstance(value, str):
            return None
        m = re.match(r"\s*campaign=([A-Za-z0-9_-]+)\s*;\s*(.*)$", value, re.S)
        if not m or not mcp_campaign(payload) or m.group(1) != mcp_campaign(payload):
            return ""
        return m.group(2).strip()
    if command(payload):
        comment = S.trailing_comment(command(payload))
        return comment[len(marker):].strip() if comment.startswith(marker) else None
    m = re.search(r"(?m)^[ \t]*(?:#|//|--)[ \t]*" + re.escape(marker) + r"[ \t]*([^\n]*)$", written_text(payload))
    return m.group(1).strip() if m else None


def bypass(payload, marker, logfile, detail=""):
    """True when a real operator bypass marker with a written reason is present.

    A marker is an audit trail, not a control: whoever can type the command can type the
    marker. So it must be a real marker (see marker_reason), it must carry a reason, the reason
    is logged with the tool and time, and CAMPAIGN_HOOKS_NO_BYPASS=1 switches every marker off.
    """
    reason = marker_reason(payload, marker)
    if reason is None:
        return False
    if os.environ.get("CAMPAIGN_HOOKS_NO_BYPASS") == "1":
        block("BLOCKED: bypass markers are switched off here (CAMPAIGN_HOOKS_NO_BYPASS=1). "
              "Fix the cause instead.")
    if len(reason) < MIN_REASON_CHARS:
        block("BLOCKED: bypass marker %s needs a reason (at least %d characters) saying why and who\n"
              "approved it. In a shell command it must be a trailing comment on the last line\n"
              "(# %s reason). In an MCP call it is the input field %s = \"campaign=<id>; reason\"\n"
              "and the id must be the campaign the call names. The reason goes to the audit log."
              % (marker, MIN_REASON_CHARS, marker, marker.rstrip(":").lower()))
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
