import importlib.util
import os
import re
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import hookinput as H  # noqa: E402

HOOKS = os.path.dirname(os.path.abspath(__file__))
STATE = os.environ.get("CAMPAIGN_STATE_DIR") or os.path.join(HOOKS, "..", "campaign-state")
LOG = H.log_path("paid-call.log")
APPROVALS_SCRIPT = os.environ.get("RUN_APPROVALS_SCRIPT") or os.path.join(HOOKS, "..", "..", "scripts", "run-approvals.py")

# provider name -> pattern that means "this statement calls that provider". The name is the key
# you approve a cap for in the bundle. Replace the list with CAMPAIGN_PAID_PROVIDERS, written as
# name=regex pairs separated by commas:  enrichment=api\.vendor-a\.example,verify=vendor-b\.example
DEFAULT_PROVIDERS = (r"apollo=apollo\.io,prospeo=prospeo\.io,bounceban=bounceban\.com,"
                     r"millionverifier=millionverifier\.com,serper=serper\.dev")
SPEND_RE = re.compile(r"(?:^|[\s;&|(])RUN_APPROVAL_SPEND=([A-Za-z0-9_.-]+):([A-Za-z0-9_.-]+):([0-9]+(?:\.[0-9]+)?)(?=$|[\s;&|)])")
SCRIPT_RE = re.compile(r"^(?:\S*/)?(?:python[0-9.]*|node|deno|bun|bash|sh|zsh)\s+(?:-[A-Za-z]\S*\s+)*([^\s-][^\s;|&]*\.(?:py|mjs|js|ts|sh))(\s|$)")
ONE_LINER_RE = re.compile(r"^(?:\S*/)?(?:python[0-9.]*\s+-c|node\s+-e|deno\s+eval|bun\s+-e|perl\s+-e|ruby\s+-e)\b")
QUOTED_RE = re.compile(r"\"(?:[^\"\\]|\\.)*\"|'[^']*'")


def providers():
    out = []
    for pair in (os.environ.get("CAMPAIGN_PAID_PROVIDERS") or DEFAULT_PROVIDERS).split(","):
        name, _, pattern = pair.partition("=")
        if name.strip() and pattern.strip():
            try:
                out.append((name.strip().lower(), re.compile(pattern.strip(), re.I)))
            except re.error:
                H.block("BLOCKED: CAMPAIGN_PAID_PROVIDERS has a pattern that is not a valid regex (%s), "
                        "so paid calls cannot be recognised." % name.strip())
    return out


def is_dry_run(segment):
    """True only for a script run that carries --dry-run as a flag of its own. Judged per
    statement: a --dry-run somewhere else in the command says nothing about this statement, and a
    one-liner or a curl has no dry run to speak of."""
    if ONE_LINER_RE.match(segment) or not SCRIPT_RE.match(segment):
        return False
    return "--dry-run" in QUOTED_RE.sub('""', segment).split()


def script_source(segment):
    m = SCRIPT_RE.match(segment)
    if not m:
        return ""
    try:
        with open(m.group(1), encoding="utf-8", errors="replace") as fh:
            return fh.read(400000)
    except OSError:
        return ""


def called(payload):
    """Provider names this tool call would spend with."""
    found = []
    known = providers()
    if H.is_mcp(payload):
        text = H.mcp_text(payload)
        return sorted({name for name, pattern in known if pattern.search(text)})
    for segment in H.command_segments(payload):
        if is_dry_run(segment):
            continue
        text = segment + "\n" + script_source(segment)
        found.extend(name for name, pattern in known if pattern.search(text))
    return sorted(set(found))


def approvals_module():
    try:
        spec = importlib.util.spec_from_file_location("run_approvals", APPROVALS_SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    except Exception as exc:
        H.block("BLOCKED: this is a paid call and scripts/run-approvals.py could not be loaded (%s), "
                "so the approval cannot be read. Unknown is not approved." % type(exc).__name__)


def main():
    payload = H.load()
    names = called(payload)
    if not names:
        H.allow()

    if H.is_mcp(payload):
        marker_text = " RUN_APPROVAL_SPEND=%s " % H.tool_input(payload).get("run_approval_spend", "")
    else:
        marker_text = H.command(payload)
    claims = {provider.lower(): (run, float(usd)) for run, provider, usd in SPEND_RE.findall(marker_text)}
    how = ("\n\nEvery paid call is approved ONCE, up front, in the run approval bundle, with a cap per provider.\n"
           "  1. python3 scripts/run-approvals.py propose --run <run> --client <name> --plan plan.json\n"
           "  2. show that one message, then: python3 scripts/run-approvals.py record --run <run> --reply \"<their words>\"\n"
           "  3. prefix the call:  RUN_APPROVAL_SPEND=<run>:<provider>:<usd estimate> <command>\n"
           "     (MCP tools: the input field run_approval_spend = \"<run>:<provider>:<usd>\")\n"
           "An approval for one provider never covers another. Over the cap, add it to the exceptions\n"
           "digest (digest-add) and carry on with the work that does not need it.")
    missing = [n for n in names if n not in claims]
    if missing:
        H.block("BLOCKED: paid call to %s with no RUN_APPROVAL_SPEND for %s.%s%s" % (
            ", ".join(names), "that provider" if len(missing) == 1 else "those providers",
            (" The one given names %s, which does not cover it." % ", ".join(sorted(claims))) if claims else "", how))

    ra = approvals_module()
    records = {}
    for name in names:
        run, usd = claims[name]
        try:
            record = records.get(run) or ra.load_record(run, STATE)
        except Exception as exc:
            H.block("BLOCKED: the approvals record for run %r could not be read (%s). Unknown is not approved." % (run, exc))
        records[run] = record
        why = ra.claim_spend(record, name, usd)
        if why:
            H.block("BLOCKED: paid call to %s is not covered by the run approval bundle: %s.%s" % (name, why, how))
    for run, record in records.items():
        try:
            ra.save_record(record, STATE)
        except Exception as exc:
            H.block("BLOCKED: could not save the spend claim (%s), so the cap would not be counted." % type(exc).__name__)
    H.log(LOG, "PAID-CALL tool=%s %s" % (H.tool_name(payload), " ".join(
        "%s=%s:$%s" % (n, claims[n][0], claims[n][1]) for n in names)))
    H.allow()


main()
