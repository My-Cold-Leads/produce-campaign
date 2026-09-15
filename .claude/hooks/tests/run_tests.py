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

HOOKS = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
passed = failed = 0

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


def run(label, hook, expect, body, env=None):
    global passed, failed
    e = dict(os.environ)
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

print(f"\nRESULT: passed={passed} failed={failed}")
sys.exit(1 if failed else 0)
