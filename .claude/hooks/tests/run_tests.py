"""Falsifiability harness: prove every gate goes RED on a known-bad input.

Fixtures are built with json.dumps so the payload is always valid JSON. An
earlier shell-quoted version produced malformed JSON, the hooks fell back to an
empty payload and allowed everything, and the run looked like a hook bug. If a
fixture is malformed the hook cannot see it, so the harness would go green for
the wrong reason. That is the failure mode this file exists to avoid.
"""
import json
import os
import subprocess
import sys

import datetime
import tempfile

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
passed = failed = 0
# Proofs and audit logs go to a throwaway directory, never into the repo.
SCRATCH = tempfile.mkdtemp()
STATE_DIR = os.path.join(SCRATCH, "campaign-state")
os.makedirs(STATE_DIR)
BASE_ENV = {"CAMPAIGN_STATE_DIR": STATE_DIR, "CAMPAIGN_HOOK_LOG_DIR": SCRATCH}

FLAG_A = "ignore_" + "global_block_list"
FLAG_B = "ignore_" + "unsubscribe_list"


def payload(cmd=None, content=None, path="/tmp/fixture.py"):
    ti = {}
    if cmd is not None:
        ti["command"] = cmd
    if content is not None:
        ti["file_path"] = path
        ti["content"] = content
    return json.dumps({"tool_name": "Bash" if cmd is not None else "Write", "tool_input": ti})


def mcp(tool, **tool_input):
    return json.dumps({"tool_name": "mcp__sender__" + tool, "tool_input": tool_input})


def proof(campaign_id, minutes_old=0, body=None, **checks):
    """Write a hardening proof the way scripts/verify-hardening.py does."""
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_old)
    ok = {"open_tracking_off": True, "click_tracking_off": True, "plain_text_on": True}
    ok.update(checks)
    path = os.path.join(STATE_DIR, "hardening-%s.ok" % campaign_id)
    with open(path, "w") as fh:
        fh.write(body if body is not None else json.dumps(
            {"campaign_id": str(campaign_id), "checks": ok, "verified_at": when.isoformat()}))
    capacity(campaign_id)


def capacity(campaign_id, minutes_old=0, body=None, passed=True, names=None):
    """Write a sending-capacity proof the way scripts/capacity-check.py does."""
    when = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=minutes_old)
    with open(os.path.join(STATE_DIR, "capacity-%s.ok" % campaign_id), "w") as fh:
        fh.write(body if body is not None else json.dumps(
            {"campaign_id": str(names or campaign_id), "passed": passed, "verified_at": when.isoformat()}))


def clear_proofs():
    for name in os.listdir(STATE_DIR):
        os.remove(os.path.join(STATE_DIR, name))


def audit(name):
    try:
        return open(os.path.join(SCRATCH, name), encoding="utf-8").read()
    except OSError:
        return ""


def run(label, hook, expect, body, env=None):
    global passed, failed
    e = dict(os.environ)
    e.pop("CAMPAIGN_HOOKS_NO_BYPASS", None)
    e.update(BASE_ENV)
    if env:
        e.update(env)
    p = subprocess.run([os.path.join(HOOKS, hook)], input=body,
                       capture_output=True, text=True, env=e)
    want = 2 if expect == "block" else 0
    if p.returncode == want:
        print(f"  PASS  {label}")
        passed += 1
    else:
        print(f"  FAIL  {label} (rc={p.returncode} want={want})")
        first = (p.stderr.strip().splitlines() or [""])[0]
        print("        " + first[:110])
        failed += 1


print("push-safe:")
run("blocks suppression-list bypass", "pretooluse-push-safe-required.sh", "block",
    payload(cmd='curl -d \'{"' + FLAG_A + '": true}\' https://api.x.com/campaigns/1/leads'))
run("blocks unsubscribe-list bypass", "pretooluse-push-safe-required.sh", "block",
    payload(cmd=FLAG_B + "=true"))
run("blocks raw lead POST", "pretooluse-push-safe-required.sh", "block",
    payload(cmd='curl -X POST https://api.x.com/campaigns/123/leads -d @leads.json'))
run("allows the shipped wrapper", "pretooluse-push-safe-required.sh", "allow",
    payload(cmd='python3 scripts/push-safe.py --campaign 1 --leads x.csv'))
run("blocks a raw curl POST to the leads endpoint", "pretooluse-push-safe-required.sh", "block",
    payload(cmd='curl -X POST "https://server.smartlead.ai/api/v1/campaigns/1/leads?api_key=$K" -d @x.json'))
RAW_SRC = 'req = Request(API + "/campaigns/%s/leads" % cid, data=body, method="POST")'
run("allows editing the wrapper's own source", "pretooluse-push-safe-required.sh", "allow",
    payload(content=RAW_SRC, path="/repo/scripts/push-safe.py"))
run("blocks the same raw POST in any other script", "pretooluse-push-safe-required.sh", "block",
    payload(content=RAW_SRC, path="/repo/scripts/quick-load.py"))
run("allows unrelated command", "pretooluse-push-safe-required.sh", "allow",
    payload(cmd='ls -la'))

print("deliverability hardening:")
run("blocks activation without proof", "pretooluse-deliverability-hardening.sh", "block",
    payload(cmd='curl -X POST /campaigns/9/status -d \'{"status":"START"}\''))
run("blocks a status payload without a URL", "pretooluse-deliverability-hardening.sh", "block",
    payload(cmd='update_status --body \'{"status": "ACTIVE"}\''))
run("allows START/ACTIVE as ordinary words", "pretooluse-deliverability-hardening.sh", "allow",
    payload(cmd='echo "START the worker, keep the ACTIVE list"'))
run("blocks lead push without proof", "pretooluse-deliverability-hardening.sh", "block",
    payload(cmd='add_leads_to_campaign 9'))
run("blocks the wrapper's --apply without proof", "pretooluse-deliverability-hardening.sh", "block",
    payload(cmd='python3 scripts/push-safe.py --campaign 9 --leads x.csv --apply'))
run("allows the wrapper's dry run", "pretooluse-deliverability-hardening.sh", "allow",
    payload(cmd='python3 scripts/push-safe.py --campaign 9 --leads x.csv'))
run("allows unrelated command", "pretooluse-deliverability-hardening.sh", "allow",
    payload(cmd='echo hello'))

print("custom field syntax:")
run("blocks spintax in a field value", "pretooluse-custom-field-syntax.sh", "block",
    payload(cmd='custom_fields: {body: "{Hola|Hey} que tal"}'))
run("blocks signature token in a field", "pretooluse-custom-field-syntax.sh", "block",
    payload(cmd='custom_fields = {sig: "%signature%"}'))
run("blocks variable nested in spintax", "pretooluse-custom-field-syntax.sh", "block",
    payload(cmd='{Hello {{first_name}}|Hi {{first_name}}}'))
run("allows a plain field value", "pretooluse-custom-field-syntax.sh", "allow",
    payload(cmd='custom_fields: {body: "Vi que abrís en Valencia"}'))
SPIN_FIELD = 'lead = {"custom_fields": {"body": "{Hola|Hey} que tal"}}'
run("blocks spintax in a field written to a code file", "pretooluse-custom-field-syntax.sh", "block",
    payload(content=SPIN_FIELD, path="/repo/scripts/build_leads.py"))
run("allows the same example in a markdown doc", "pretooluse-custom-field-syntax.sh", "allow",
    payload(content="Never do this:\n```\n" + SPIN_FIELD + "\n```", path="/repo/docs/rules.md"))

print("abstention:")
run("blocks the token in a push payload", "pretooluse-abstention-guard.sh", "block",
    payload(cmd='POST /campaigns/1/leads custom_fields {obs: "NOT_FOUND"}'))
run("blocks the token in custom_fields sent with a POST", "pretooluse-abstention-guard.sh", "block",
    payload(content='requests.post(url, json={"custom_fields": {"obs": "NOT_FOUND"}})'))
run("allows the token outside a push", "pretooluse-abstention-guard.sh", "allow",
    payload(cmd='grep NOT_FOUND results.json'))
run("allows custom_fields and the token with no send verb", "pretooluse-abstention-guard.sh", "allow",
    payload(cmd='grep -c NOT_FOUND custom_fields.json'))

FIX = {"LLM_ENDPOINT_RE": r"llm-vendor\.example/v1/messages"}
URL = "https://llm-vendor.example/v1/messages"
print("prompt cache (fixture endpoint via LLM_ENDPOINT_RE):")
run("blocks an uncached loop", "pretooluse-prompt-cache-guard.sh", "block",
    payload(content=f'for r in rows:\n    post("{URL}", json=b)'), env=FIX)
run("allows a cached loop", "pretooluse-prompt-cache-guard.sh", "allow",
    payload(content=f'for r in rows:\n    b["system"]=[{{"cache_control":{{"type":"ephemeral"}}}}]\n    post("{URL}", json=b)'), env=FIX)
run("allows a single call", "pretooluse-prompt-cache-guard.sh", "allow",
    payload(content=f'post("{URL}", json=b)'), env=FIX)

print("durable writes:")
run("blocks buffer-then-flush", "pretooluse-durable-writes.sh", "block",
    payload(content='out=[]\nfor c in cos:\n    r=get("https://serper.dev/search")\n    out.append(r)\ndb.insert(out)'))
run("allows a per-record write", "pretooluse-durable-writes.sh", "allow",
    payload(content='for c in cos:\n    r=get("https://serper.dev/search")\n    db.insert(r)\n    out.append(r)'))

ALL_HOOKS = ("pretooluse-push-safe-required.sh", "pretooluse-deliverability-hardening.sh", "pretooluse-custom-field-syntax.sh",
             "pretooluse-abstention-guard.sh", "pretooluse-prompt-cache-guard.sh", "pretooluse-durable-writes.sh")
print("fail closed on an envelope the hook cannot parse:")
for h in ALL_HOOKS:
    run("%s blocks malformed JSON" % h, h, "block", '{"tool_name": "Bash", "tool_input": {"command": "curl ')
run("blocks an empty envelope", "pretooluse-push-safe-required.sh", "block", "")
run("blocks a tool_input that is not an object", "pretooluse-deliverability-hardening.sh", "block",
    json.dumps({"tool_name": "Bash", "tool_input": "curl -X POST /campaigns/9/status"}))

print("MCP tool calls are inspected too:")
run("blocks a lead push made through an MCP tool", "pretooluse-push-safe-required.sh", "block",
    mcp("add_leads_to_campaign", campaign_id=9, lead_list=[{"email": "ana@example.com"}]))
run("blocks a suppression bypass inside an MCP tool input", "pretooluse-push-safe-required.sh", "block",
    mcp("update_settings", campaign_id=9, settings={FLAG_A: True}))
run("allows a read-only MCP tool", "pretooluse-push-safe-required.sh", "allow", mcp("get_campaign_leads", campaign_id=9))
run("blocks the abstention token in an MCP lead push", "pretooluse-abstention-guard.sh", "block",
    mcp("add_leads_to_campaign", campaign_id=9, lead_list=[{"email": "ana@example.com", "custom_fields": {"obs": "NOT_FOUND"}}]))
run("blocks spintax in a custom field sent through an MCP tool", "pretooluse-custom-field-syntax.sh", "block",
    mcp("add_leads_to_campaign", campaign_id=9, lead_list=[{"custom_fields": {"body": "{Hola|Hey} que tal"}}]))
run("blocks an MCP campaign start without proof", "pretooluse-deliverability-hardening.sh", "block",
    mcp("update_campaign_status", campaign_id=9, status="START"))
run("allows an MCP pause without proof (pausing is the safety action)", "pretooluse-deliverability-hardening.sh", "allow",
    mcp("update_campaign_status", campaign_id=9, status="PAUSED"))

print("hardening proof is scoped to one campaign:")
START_9 = payload(cmd='curl -X POST /campaigns/9/status -d \'{"status":"START"}\'')
APPLY_9 = payload(cmd='python3 scripts/push-safe.py --campaign 9 --leads x.csv --approval a.json --apply')
proof(8)
run("RED: a fresh proof for campaign 8 does not unlock a start on campaign 9", "pretooluse-deliverability-hardening.sh", "block", START_9)
run("RED: a fresh proof for campaign 8 does not unlock a push to campaign 9", "pretooluse-deliverability-hardening.sh", "block", APPLY_9)
run("RED: nor an MCP start on campaign 9", "pretooluse-deliverability-hardening.sh", "block",
    mcp("update_campaign_status", campaign_id=9, status="START"))
run("the proof for campaign 8 unlocks campaign 8", "pretooluse-deliverability-hardening.sh", "allow",
    payload(cmd='python3 scripts/push-safe.py --campaign 8 --leads x.csv --approval a.json --apply'))
run("RED: a send with no readable campaign id is blocked even with a proof on disk", "pretooluse-deliverability-hardening.sh", "block",
    payload(cmd='python3 scripts/push-safe.py --campaign "$CID" --leads x.csv --apply'))
proof(9)
run("a proof for campaign 9 unlocks the start", "pretooluse-deliverability-hardening.sh", "allow", START_9)
run("and the wrapper's --apply", "pretooluse-deliverability-hardening.sh", "allow", APPLY_9)
run("and the MCP start", "pretooluse-deliverability-hardening.sh", "allow", mcp("update_campaign_status", campaign_id=9, status="START"))
proof(9, body="")
run("RED: an empty file made with touch is not a proof", "pretooluse-deliverability-hardening.sh", "block", START_9)
proof(9, minutes_old=500)
run("RED: a stale proof is refused", "pretooluse-deliverability-hardening.sh", "block", START_9)
proof(9, plain_text_on=False)
run("RED: a proof that shows plain text off is refused", "pretooluse-deliverability-hardening.sh", "block", START_9)
proof(9, body=json.dumps({"campaign_id": "8", "checks": {"open_tracking_off": True, "click_tracking_off": True, "plain_text_on": True},
                          "verified_at": datetime.datetime.now(datetime.timezone.utc).isoformat()}))
run("RED: a proof copied from another campaign is refused", "pretooluse-deliverability-hardening.sh", "block", START_9)
clear_proofs()

print("bypass markers need a reason, and the reason is logged:")
RAW = 'curl -X POST https://api.x.com/campaigns/123/leads -d @leads.json'
run("RED: a marker with no reason is blocked", "pretooluse-push-safe-required.sh", "block", payload(cmd=RAW + "  # PUSH_SAFE_OK:"))
run("RED: a marker with a token reason is blocked", "pretooluse-push-safe-required.sh", "block", payload(cmd=RAW + "  # PUSH_SAFE_OK: ok"))
run("a marker with a real reason is allowed", "pretooluse-push-safe-required.sh", "allow",
    payload(cmd=RAW + "  # PUSH_SAFE_OK: one-off repair approved by the account owner"))
if "reason=one-off repair approved by the account owner" in audit("push-safe-bypass.log"):
    print("  PASS  the reason is in the audit log"); passed += 1
else:
    print("  FAIL  the reason is in the audit log"); failed += 1
run("RED: markers can be switched off entirely", "pretooluse-push-safe-required.sh", "block",
    payload(cmd=RAW + "  # PUSH_SAFE_OK: one-off repair approved by the account owner"), env={"CAMPAIGN_HOOKS_NO_BYPASS": "1"})
run("RED: the suppression-list rule ignores every marker", "pretooluse-push-safe-required.sh", "block",
    payload(cmd=FLAG_B + "=true  # PUSH_SAFE_OK: one-off repair approved by the account owner"))
run("a hardening marker with a reason is allowed and logged", "pretooluse-deliverability-hardening.sh", "allow",
    payload(cmd='curl -X POST /campaigns/9/status -d \'{"status":"START"}\'  # HARDENING_OK: verified by hand in the platform UI today'))
if "campaigns=9" in audit("hardening-bypass.log"):
    print("  PASS  the hardening bypass log names the campaign"); passed += 1
else:
    print("  FAIL  the hardening bypass log names the campaign"); failed += 1


def expect(label, ok):
    global passed, failed
    print("  %s  %s" % ("PASS" if ok else "FAIL", label))
    passed, failed = passed + bool(ok), failed + (not ok)


PUSH, HARD = "pretooluse-push-safe-required.sh", "pretooluse-deliverability-hardening.sh"
REASON = "one-off repair approved by the account owner"

print("a bypass marker must be a real trailing comment, and the MCP flag must name the campaign:")
run("RED: the marker inside a quoted string is not a marker", PUSH, "block",
    payload(cmd=RAW + ' -H "X-Note: # PUSH_SAFE_OK: %s"' % REASON))
run("RED: the marker echoed on an earlier line is not a marker", PUSH, "block",
    payload(cmd='echo "# PUSH_SAFE_OK: %s"\n%s' % (REASON, RAW)))
run("RED: the marker as an env prefix is not a marker", PUSH, "block", payload(cmd='PUSH_SAFE_OK="%s" %s' % (REASON, RAW)))
run("RED: the marker in a comment that is not on the last line", PUSH, "block", payload(cmd="# PUSH_SAFE_OK: %s\n%s" % (REASON, RAW)))
run("a trailing comment after a continued command is a marker", PUSH, "allow",
    payload(cmd="curl -X POST \\\n  https://api.x.com/campaigns/123/leads -d @leads.json  # PUSH_SAFE_OK: " + REASON))
LEADS_MCP = dict(campaign_id=9, lead_list=[{"email": "ana@example.com"}])
run("RED: an MCP push with a bare reason and no campaign is blocked", PUSH, "block", mcp("add_leads_to_campaign", push_safe_ok=REASON, **LEADS_MCP))
run("RED: an MCP flag naming another campaign is blocked", PUSH, "block",
    mcp("add_leads_to_campaign", push_safe_ok="campaign=8; " + REASON, **LEADS_MCP))
run("RED: an MCP flag naming the campaign with no reason is blocked", PUSH, "block",
    mcp("add_leads_to_campaign", push_safe_ok="campaign=9; ok", **LEADS_MCP))
run("RED: the marker hidden in the lead data is not a flag", PUSH, "block",
    mcp("add_leads_to_campaign", campaign_id=9, lead_list=[{"email": "a@example.com", "note": "# PUSH_SAFE_OK: " + REASON}]))
run("an MCP flag naming the campaign with a reason is allowed and logged", PUSH, "allow",
    mcp("add_leads_to_campaign", push_safe_ok="campaign=9; " + REASON, **LEADS_MCP))

print("the statement reader: hidden actions are still seen:")
proof(8)
for label, cmd in (
        ("a backslash continuation", "curl -X POST \\\n  https://api.x.com/campaigns/123/leads \\\n  -d @leads.json"),
        ("an env prefix", "API_KEY=abc env TZ=UTC curl -X POST https://api.x.com/campaigns/123/leads -d @leads.json"),
        ("bash -c", "bash -c 'curl -X POST https://api.x.com/campaigns/123/leads -d @leads.json'"),
        ("bash -lc inside an if", "if true; then bash -lc \"curl -X POST https://api.x.com/campaigns/123/leads -d @l.json\"; fi"),
        ("xargs", "cat ids.txt | xargs -I{} curl -X POST https://api.x.com/campaigns/{}/leads -d @leads.json"),
        ("a pipe into a shell", "echo 'curl -X POST https://api.x.com/campaigns/123/leads -d @l.json' | bash"),
        ("a heredoc fed to an interpreter", "python3 - <<'EOF'\nrequests.request('POST', 'https://api.x.com/campaigns/123/leads', json=b)\nEOF"),
        ("find -exec", "find . -name '*.json' -exec curl -X POST https://api.x.com/campaigns/123/leads -d @{} \\;"),
        ("awk system(", "awk 'BEGIN{system(\"curl -X POST https://api.x.com/campaigns/123/leads -d @l.json\")}'"),
        ("a command substitution inside a grep", "grep ok $(curl -X POST https://api.x.com/campaigns/123/leads -d @l.json)")):
    run("RED: a raw push behind %s is blocked" % label, PUSH, "block", payload(cmd=cmd))
run("RED: the wrapper's --apply on a continued line needs the proof", HARD, "block",
    payload(cmd="python3 scripts/push-safe.py --campaign 9 --leads x.csv \\\n  --approval a.json \\\n  --apply"))

print("read-only commands are never blocked:")
ENDPOINT = "POST https://api.x.com/campaigns/123/leads"
START_TEXT = '/campaigns/9/status {"status":"START"}'
for label, cmd in (
        ("grep", "grep -rn '%s' scripts/" % ENDPOINT), ("cat", "cat notes.txt # %s" % ENDPOINT),
        ("sed -n", "sed -n '/%s/p' notes.txt" % "POST .campaigns.123.leads"), ("git show", "git show HEAD~1 -- 'POST /campaigns/123/leads'"),
        ("git log -p piped to grep", "git log -p | grep -n '%s'" % ENDPOINT), ("bash -n", "bash -n scripts/old-push.sh '%s'" % ENDPOINT),
        ("find without -exec", "find . -name '*campaigns*leads*POST*'"), ("awk that only prints", "awk '/POST .campaigns.1.leads/ {print $1}' log.txt")):
    run("%s that mentions a raw push is allowed" % label, PUSH, "allow", payload(cmd=cmd))
    run("%s that mentions a campaign start is allowed" % label, HARD, "allow", payload(cmd=cmd.replace(ENDPOINT, START_TEXT)))
run("a heredoc that only writes notes to a file is allowed", PUSH, "allow",
    payload(cmd="cat > notes.md <<'EOF'\nNever do: curl -X POST https://api.x.com/campaigns/123/leads -d @l.json\nEOF"))
run("RED: sed -i is not read-only", PUSH, "block", payload(cmd="sed -i 's/x/y/' f; curl -X POST https://api.x.com/campaigns/123/leads -d @l.json"))
run("RED: a read-only command does not cover the push after it", PUSH, "block",
    payload(cmd="grep -c a leads.json && curl -X POST https://api.x.com/campaigns/123/leads -d @leads.json"))
run("RED: an echo redirected into a script is still read", PUSH, "block",
    payload(cmd="echo 'curl -X POST https://api.x.com/campaigns/123/leads -d @l.json' > load.sh"))

print("go-live needs the sending-capacity proof as well:")
clear_proofs()
proof(9)
os.remove(os.path.join(STATE_DIR, "capacity-9.ok"))
run("RED: a start with a hardening proof and no capacity proof is blocked", HARD, "block", START_9)
run("RED: so is the MCP start", HARD, "block", mcp("update_campaign_status", campaign_id=9, status="START"))
run("a lead load into the draft does not need the capacity proof", HARD, "allow", APPLY_9)
capacity(9, passed=False)
run("RED: a capacity proof that did not pass is refused", HARD, "block", START_9)
capacity(9, names=8)
run("RED: a capacity proof for another campaign is refused", HARD, "block", START_9)
capacity(9, minutes_old=3000)
run("RED: a stale capacity proof is refused", HARD, "block", START_9)
capacity(9, body="")
run("RED: an empty capacity file is refused", HARD, "block", START_9)
capacity(9)
run("hardening proof plus capacity proof unlock the start", HARD, "allow", START_9)
clear_proofs()

print("paid calls read the run approval bundle (fixture providers):")
import importlib.util  # noqa: E402
REPO = os.path.dirname(os.path.dirname(HOOKS))
_spec = importlib.util.spec_from_file_location("run_approvals", os.path.join(REPO, "scripts", "run-approvals.py"))
ra = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ra)
PAID = "pretooluse-paid-call-approved.sh"
PENV = {"CAMPAIGN_PAID_PROVIDERS": r"enrichment=api\.vendor-a\.example,verify=api\.vendor-b\.example"}
CALL_A = "curl -s https://api.vendor-a.example/v1/people -d @batch.json"
CALL_B = "curl -s https://api.vendor-b.example/v1/verify -d @batch.json"
NOW = datetime.datetime.now(datetime.timezone.utc)


def bundle(run_key, hours=72, declined=(), caps=None, recorded=True):
    plan = {"scope": "fixture scope", "cohort_target": 50, "copy_author": "existing copy only",
            "caps": caps or {"enrichment": 10, "verify": 5}, "contact_search": {"none": True, "reason": "fixture"}}
    rec = {"run": run_key, "client": "ACME", "bundle": None, "decisions": [], "digest": [],
           "pending": ra.new_pending("bundle", ra.build_bundle_items(plan), hours, NOW - datetime.timedelta(hours=1))}
    if recorded:
        reply = "yes" + "".join("\n%d no" % i["n"] for i in rec["pending"]["items"] if i["key"] in declined)
        rec, _ = ra.apply_reply(rec, reply, (NOW - datetime.timedelta(minutes=30)).isoformat(), NOW)
    ra.save_record(rec, STATE_DIR)


def spent(run_key, provider):
    rec = ra.load_record(run_key, STATE_DIR)
    return [d.get("spent_usd") for d in rec["decisions"] if d["kind"] == "spend" and d["key"] == provider][0]


run("RED: a paid call with no approval marker is blocked", PAID, "block", payload(cmd=CALL_A), env=PENV)
run("RED: a marker for a run with no bundle is blocked", PAID, "block", payload(cmd="RUN_APPROVAL_SPEND=run-a:enrichment:2 " + CALL_A), env=PENV)
bundle("run-a", recorded=False)
run("RED: a bundle that was proposed but never answered is blocked", PAID, "block", payload(cmd="RUN_APPROVAL_SPEND=run-a:enrichment:2 " + CALL_A), env=PENV)
bundle("run-a")
run("a recorded bundle covers the provider it names", PAID, "allow", payload(cmd="RUN_APPROVAL_SPEND=run-a:enrichment:2 " + CALL_A), env=PENV)
expect("and the claim is counted against the cap", spent("run-a", "enrichment") == 2.0)
run("RED: the enrichment key does not cover a call to the verification provider", PAID, "block",
    payload(cmd="RUN_APPROVAL_SPEND=run-a:enrichment:2 " + CALL_B), env=PENV)
run("RED: one key does not cover two providers in one command", PAID, "block",
    payload(cmd="RUN_APPROVAL_SPEND=run-a:enrichment:2 " + CALL_A + " && " + CALL_B), env=PENV)
run("RED: over the cumulative cap is blocked", PAID, "block", payload(cmd="RUN_APPROVAL_SPEND=run-a:enrichment:9 " + CALL_A), env=PENV)
run("RED: another run's bundle is not read", PAID, "block", payload(cmd="RUN_APPROVAL_SPEND=run-b:enrichment:1 " + CALL_A), env=PENV)
bundle("run-c", declined=("verify",))
run("RED: a declined provider is not covered", PAID, "block", payload(cmd="RUN_APPROVAL_SPEND=run-c:verify:1 " + CALL_B), env=PENV)
bundle("run-d", hours=0.2)
run("RED: an expired bundle is not covered", PAID, "block", payload(cmd="RUN_APPROVAL_SPEND=run-d:enrichment:1 " + CALL_A), env=PENV)
with open(os.path.join(STATE_DIR, "run-approvals-run-e.json"), "w") as fh:
    fh.write("{broken")
run("RED: an unreadable record is blocked", PAID, "block", payload(cmd="RUN_APPROVAL_SPEND=run-e:enrichment:1 " + CALL_A), env=PENV)
run("RED: the marker echoed instead of set is not a marker for the call", PAID, "block",
    payload(cmd=CALL_A + " ; echo done-RUN_APPROVAL_SPEND=run-a:enrichment:1"), env=PENV)
run("RED: an MCP call to the provider with no approval is blocked", PAID, "block",
    mcp("fetch", url="https://api.vendor-a.example/v1/people"), env=PENV)
run("an MCP call with the approval field is allowed", PAID, "allow",
    mcp("fetch", url="https://api.vendor-a.example/v1/people", run_approval_spend="run-a:enrichment:1"), env=PENV)
run("RED: malformed input is blocked", PAID, "block", '{"tool_name": "Bash", "tool_input": {"command": "curl ', env=PENV)

print("paid calls: each statement is judged by itself:")
SCRIPT = os.path.join(SCRATCH, "enrich.py")
with open(SCRIPT, "w") as fh:
    fh.write('import urllib.request\nURL = "https://api.vendor-a.example/v1/people"\n')
run("RED: a script whose source calls the provider is blocked", PAID, "block", payload(cmd="python3 %s --limit 50" % SCRIPT), env=PENV)
run("the same script with --dry-run is allowed", PAID, "allow", payload(cmd="python3 %s --limit 50 --dry-run" % SCRIPT), env=PENV)
run("RED: --dry-run on one statement does not cover the next one", PAID, "block",
    payload(cmd="python3 %s --dry-run && %s" % (SCRIPT, CALL_A)), env=PENV)
run("RED: --dry-run inside a quoted string is not a flag", PAID, "block",
    payload(cmd="python3 %s --note '--dry-run'" % SCRIPT), env=PENV)
run("RED: --dry-run typed after a curl does not make it a dry run", PAID, "block", payload(cmd=CALL_A + " --dry-run"), env=PENV)
run("RED: --dry-run in a trailing comment does not count", PAID, "block", payload(cmd=CALL_A + "  # --dry-run"), env=PENV)
run("RED: find -exec that calls the provider is blocked", PAID, "block",
    payload(cmd="find batches -name '*.json' -exec curl -s https://api.vendor-a.example/v1/people -d @{} \\;"), env=PENV)
run("RED: awk system( that calls the provider is blocked", PAID, "block",
    payload(cmd="awk '{system(\"curl -s https://api.vendor-a.example/v1/people?q=\" $1)}' ids.txt"), env=PENV)
run("find with no -exec that only names the provider is allowed", PAID, "allow", payload(cmd="find . -name '*api.vendor-a.example*'"), env=PENV)
run("awk that only prints lines naming the provider is allowed", PAID, "allow",
    payload(cmd="awk '/api.vendor-a.example/ {print $2}' requests.log"), env=PENV)
run("python -c with no provider host is allowed", PAID, "allow", payload(cmd="python3 -c 'import json; print(json.dumps({\"a\": 1}))'"), env=PENV)
run("RED: python -c that calls the provider is blocked", PAID, "block",
    payload(cmd="python3 -c 'import urllib.request as u; u.urlopen(\"https://api.vendor-a.example/v1/people\")'"), env=PENV)
run("RED: python -c that calls the provider is blocked even with --dry-run typed after it", PAID, "block",
    payload(cmd="python3 -c 'import urllib.request as u; u.urlopen(\"https://api.vendor-a.example/v1/people\")' --dry-run"), env=PENV)
run("grep for the provider host is allowed", PAID, "allow", payload(cmd="grep -rn 'api.vendor-a.example' scripts/"), env=PENV)
run("git show of a diff naming the provider is allowed", PAID, "allow", payload(cmd="git show HEAD -- 'api.vendor-a.example'"), env=PENV)
run("an unrelated command is allowed", PAID, "allow", payload(cmd="ls -la"), env=PENV)

print("a copy sign-off never opens the push hook:")
rec = ra.load_record("run-a", STATE_DIR)
rec["decisions"].append({"kind": "copy_signoff_draft_push", "key": "draft_push", "verdict": "approved", "campaign_ids": ["123", "9"],
                         "copy_fingerprint": "f" * 64, "leads_sha256": "a" * 64, "account": "77",
                         "decided_at": NOW.isoformat(), "expires_at": (NOW + datetime.timedelta(hours=20)).isoformat()})
ra.save_record(rec, STATE_DIR)
run("RED: a raw HTTP push to a signed-off campaign is still blocked", PUSH, "block", payload(cmd=RAW))
run("RED: a raw push that names the run is still blocked", PUSH, "block", payload(cmd="RUN_APPROVALS=run-a COPY_SIGNOFF=run-a " + RAW))
run("RED: a direct MCP push to a signed-off campaign is still blocked", PUSH, "block", mcp("add_leads_to_campaign", **LEADS_MCP))
run("RED: an MCP push carrying the run as a field is still blocked", PUSH, "block",
    mcp("add_leads_to_campaign", run_approvals="run-a", copy_signoff="run-a", **LEADS_MCP))
run("RED: the sign-off does not stand in for the hardening proof on a start", HARD, "block", START_9)

print(f"\nRESULT: passed={passed} failed={failed}")
sys.exit(1 if failed else 0)
