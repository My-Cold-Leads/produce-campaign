"""Statement-level reading of a shell command, shared by the gate hooks.

A gate that greps the whole command string makes two kinds of mistake. It blocks commands that
only READ (a grep for an endpoint name, a cat of a script, a git show of an old diff), and it is
blind to commands that hide the action (a backslash continuation, an env prefix, bash -c, xargs,
an if, a pipe). This module splits the command into statements, peels the wrappers off each one,
and hands the gates only the statements that can actually do something.

  active_text(cmd)   the text the gates should scan
  segments(cmd)      the same statements as a list, for gates that judge one statement at a time

Rules:
  - A backslash at the end of a line joins the next line.
  - A heredoc whose command only writes a file (cat or tee, not piped into an interpreter) has
    its body dropped: that body is data. A heredoc fed to a shell or an interpreter keeps its body.
  - Statements split on newline ; && || & | outside quotes.
  - if / then / while / ! / { / ( , VAR=value prefixes, and env / nohup / command / exec / sudo /
    nice / time / xargs are peeled off before a statement is judged.
  - bash -c '...' (sh, zsh, eval too) is opened and its inside is read as a command.
  - A read-only statement is dropped: grep, cat, head, tail, less, wc, ls, stat, diff, sort, cut,
    sed -n (never sed -i), git show / log / diff / status / grep / blame, bash -n, echo and
    printf. It is NOT read-only when it runs something (a command substitution, awk with
    system( or a pipe, find with -exec or -delete), writes a file (a redirect), or feeds the
    next statement when that one is a shell or an interpreter.

When in doubt a statement is kept. Dropping is the exception and has to be earned.
"""
import re

CONTINUATION_RE = re.compile(r"\\\r?\n")
HEREDOC_RE = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)(\w+)\1")
INTERPRETER = r"(?:\S*/)?(?:(?:ba|z|da|k)?sh|python[0-9.]*|node|deno|bun|perl|ruby|php)"
INTERPRETER_RE = re.compile(r"^" + INTERPRETER + r"(\s|$)")
PIPE_TO_INTERPRETER_RE = re.compile(r"\|\s*(?:xargs\s+(?:-\S+\s+)*)?" + INTERPRETER + r"\b")
ENV_PREFIX_RE = re.compile(r"^(?:[A-Za-z_]\w*=(?:\"[^\"]*\"|'[^']*'|\$\((?:[^()]|\([^()]*\))*\)|`[^`]*`|\S*)\s+)+")
CONTROL_RE = re.compile(r"^(?:(?:if|then|else|elif|do|while|until|!|\{|\()\s+)+")
WRAPPER_RE = re.compile(r"^(env|nohup|command|exec|sudo|nice|time|xargs)\s+")
XARGS_VALUE_OPTS = frozenset(("-I", "-n", "-P", "-L", "-d", "-s", "-E", "-a"))
SHELL_C_RE = re.compile(r"^(?:\S*/)?(?:ba|z|da|k)?sh\s+(?:-[A-Za-z]+\s+)*-[A-Za-z]*c[A-Za-z]*\s+(.*)$", re.S)
EVAL_RE = re.compile(r"^eval\s+(.*)$", re.S)
QUOTED_RE = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")
REDIRECT_RE = re.compile(r"(?<![0-9&<])[0-9]?>>?(?!&)\s*(\S+)")

READ_ONLY = frozenset("""grep egrep fgrep rg ag cat head tail less more wc ls stat file diff cmp sort uniq cut tr
    test [ true false pwd which type basename dirname date echo printf nl column jq""".split())
GIT_READ_ONLY = frozenset("show log diff status grep blame ls-files rev-parse cat-file shortlog describe".split())
FIND_RUNS = re.compile(r"(?:^|\s)-(exec|execdir|ok|okdir|delete|fprint\w*|fls)\b")
AWK_RUNS = re.compile(r"system\s*\(|getline|\|\s*\"|\|&|print[^|\n]*\|")


def join_continuations(text):
    return CONTINUATION_RE.sub(" ", text or "")


def unwrap(stmt):
    """Peel control keywords, VAR=value prefixes and wrapper commands off the front."""
    s = stmt.strip()
    for _ in range(12):
        before = s
        s = CONTROL_RE.sub("", s, count=1).strip()
        s = ENV_PREFIX_RE.sub("", s, count=1).strip()
        m = WRAPPER_RE.match(s)
        if m:
            kind, rest = m.group(1), s[m.end():]
            while True:
                tok = re.match(r"(\S+)\s*", rest)
                if not tok:
                    break
                word = tok.group(1)
                if kind == "xargs" and word in XARGS_VALUE_OPTS:
                    two = re.match(r"\S+\s*(\S+\s*)?", rest)
                    rest = rest[two.end():]
                elif word.startswith("-") or (kind == "env" and re.match(r"[A-Za-z_]\w*=", word)):
                    rest = rest[tok.end():]
                else:
                    break
            s = rest.strip()
        if s == before:
            break
    return s


def strip_heredoc_data(text):
    """Drop heredoc bodies that are only written to a file. Keep the ones that are run."""
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        line = lines[i]
        out.append(line)
        i += 1
        m = HEREDOC_RE.search(line)
        if not m:
            continue
        head = re.match(r"(?:\S*/)?([\w.-]+)", unwrap(line))
        data_only = bool(head) and head.group(1) in ("cat", "tee") and not PIPE_TO_INTERPRETER_RE.search(line)
        body = []
        while i < len(lines):
            if lines[i].strip() == m.group(2):
                i += 1
                break
            body.append(lines[i])
            i += 1
        if not data_only:
            out.extend(body)
    return "\n".join(out)


def split_statements(text):
    """[(statement, separator that followed it)] split outside quotes."""
    out, cur, i, quote = [], "", 0, ""
    while i < len(text):
        c = text[i]
        two = text[i:i + 2]
        if quote:
            cur += c
            if c == "\\" and quote == '"' and i + 1 < len(text):
                cur += text[i + 1]
                i += 1
            elif c == quote:
                quote = ""
        elif c in "'\"":
            quote = c
            cur += c
        elif c == "\\" and i + 1 < len(text):
            cur += two
            i += 1
        elif two in ("&&", "||"):
            out.append((cur, two))
            cur = ""
            i += 1
        elif c in ";\n|":
            out.append((cur, c))
            cur = ""
        elif c == "&" and not (cur.endswith(">") or text[i + 1:i + 2] == ">" or re.search(r"[0-9]?>$", cur)):
            out.append((cur, c))
            cur = ""
        else:
            cur += c
        i += 1
    out.append((cur, ""))
    return [(s.strip(), sep) for s, sep in out if s.strip()]


def is_read_only(stmt):
    """True only when the (already unwrapped) statement can do nothing but read and print."""
    if "$(" in stmt or "`" in stmt or "<(" in stmt or ">(" in stmt:
        return False
    bare = QUOTED_RE.sub('""', stmt)
    for target in REDIRECT_RE.findall(bare):
        if target != "/dev/null":
            return False
    words = bare.split()
    if not words:
        return True
    name = words[0].rsplit("/", 1)[-1]
    flags = [w for w in words[1:] if w.startswith("-")]
    if name in READ_ONLY:
        return True
    if name == "sed":
        return any(re.match(r"^-[a-zA-Z]*n[a-zA-Z]*$", f) for f in flags) and not any(
            re.match(r"^(-[a-zA-Z]*i|--in-place)", f) for f in flags)
    if name == "git":
        sub = next((w for w in words[1:] if not w.startswith("-")), "")
        return sub in GIT_READ_ONLY
    if name in ("bash", "sh", "zsh", "dash", "ksh"):
        return any(re.match(r"^-[a-zA-Z]*n[a-zA-Z]*$", f) for f in flags) and not any(
            re.match(r"^-[a-zA-Z]*c", f) for f in flags)
    if name == "find":
        return not FIND_RUNS.search(bare)
    if name in ("awk", "gawk", "mawk"):
        return not AWK_RUNS.search(stmt)
    return False


def _strip_outer_quotes(text):
    text = text.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in "'\"":
        return text[1:-1]
    m = re.match(r"^(['\"])(.*?)\1(\s|$)", text, re.S)
    return m.group(2) if m else text


def _walk(cmd, depth=0):
    """[(raw statement, separator, unwrapped statements it stands for)] for the statements kept."""
    text = strip_heredoc_data(join_continuations(cmd))
    parts = split_statements(text)
    kept = []
    for pos, (raw, sep) in enumerate(parts):
        stmt = unwrap(raw)
        if not stmt:
            continue
        inner = SHELL_C_RE.match(stmt) or EVAL_RE.match(stmt)
        if inner and depth < 4:
            inside = [u for _, _, us in _walk(_strip_outer_quotes(inner.group(1)), depth + 1) for u in us]
            if inside:
                kept.append((raw, sep, inside))
            continue
        feeds_interpreter = False
        if sep == "|" and pos + 1 < len(parts):
            feeds_interpreter = bool(INTERPRETER_RE.match(unwrap(parts[pos + 1][0])))
        if is_read_only(stmt) and not feeds_interpreter:
            continue
        kept.append((raw, sep, [stmt]))
    return kept


def segments(cmd):
    """The statements of a command that can act, unwrapped, in order. Read-only ones are gone.
    A bash -c '...' is replaced by the statements inside it."""
    return [u for _, _, us in _walk(cmd) for u in us]


def active_text(cmd):
    """The acting statements as they were typed, with their separators, for pattern scans."""
    return "".join(raw + (sep if sep and sep != "\n" else "\n") for raw, sep, _ in _walk(cmd))


def trailing_comment(cmd):
    """The text of a real shell comment on the last line of the command, or ''. A '#' inside
    quotes, inside a word, or on an earlier line is not a trailing comment."""
    text = join_continuations(cmd).rstrip()
    start = text.rfind("\n") + 1
    quote, i, last = "", 0, len(text)
    comment_at = -1
    while i < last:
        c = text[i]
        if quote:
            if c == "\\" and quote == '"':
                i += 1
            elif c == quote:
                quote = ""
        elif c in "'\"":
            quote = c
        elif c == "\\":
            i += 1
        elif c == "\n":
            comment_at = -1
        elif c == "#" and comment_at < 0 and (i == 0 or text[i - 1] in " \t\n;"):
            comment_at = i
            nl = text.find("\n", i)
            if nl == -1:
                break
            i = nl
            comment_at = -1
            continue
        i += 1
    if comment_at < start or quote:
        return ""
    return text[comment_at + 1:].strip()
