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

print(f"\nRESULT: passed={passed} failed={failed}")
sys.exit(1 if failed else 0)
