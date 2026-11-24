# Run approval bundle and the human touchpoints

Read this at the start of every run, before any data work and before any paid call.

## The rule

Ask for every approval the run needs ONCE, up front. Save the answer. Every later gate reads the saved answer instead of asking again. A run has 4 to 6 human touchpoints, never one per step:

| # | Touchpoint | When | Command |
|---|---|---|---|
| 1 | Run approval bundle | Start of the run | `run-approvals.py propose`, then `record` |
| 2 | Offer and 10 real examples | Only if the offer or the prompt is new or changed | `propose-offer`, then `record` |
| 3 | Final copy sign-off plus the DRAFT push of the named campaigns, in one reply | After pre-push validation | `propose-signoff`, then `record` |
| 4 | Go-live | After post-push review, hardening and the capacity check | `propose-go-live`, then `record` |
| 5 | Exceptions digest | Only if something tripped | `digest-add` as you go, `digest-show` once |

A sixth touch exists only when answering the digest raises something new.

A yes in any wording counts. Never ask the user to type a set phrase. Never ask "shall I continue?" between steps that need no decision.

## Touchpoint 1: what the bundle carries

Write `plan.json`, then run `python3 scripts/run-approvals.py propose --run <run> --client <name> --plan plan.json` and show the message it prints, unchanged.

```json
{
  "scope": "segments, regions and roles in this run",
  "cohort_target": 400,
  "copy_author": "who writes new copy, or 'existing copy only'",
  "caps": {"<provider>": 25},
  "skips": [{"step": "7", "label": "prompt test loop", "condition": "prompt hash unchanged since the previous approved run"}],
  "contact_search": {"methods": ["people search", "enrichment"], "roles": ["operations director"], "max_companies": 400},
  "false_positive_gates": ["prompt cache"]
}
```

The message also states three standing policies: a logged false-positive bypass only with a second reviewer and a fixture, never for suppression, hardening, pushes or sends; a lead you are unsure about is paused and listed in the digest, never sent; steps that need no decision run straight through.

Then paste the user's reply: `python3 scripts/run-approvals.py record --run <run> --reply "<their words>"`. Paste what they wrote. Do not write it for them.

## What the code holds

- The record belongs to one run. A decision for another run is never found.
- Every decision expires (72 hours by default for the bundle, 24 for the copy sign-off and go-live).
- A declined item is saved as declined and never counts. If the reply names a different amount than the cap shown, that item stays open and is asked again.
- A spend approval covers only the provider it names, up to a cumulative cap. The paid-call hook reads it: prefix the call with `RUN_APPROVAL_SPEND=<run>:<provider>:<usd>`.
- A skip is covered only with evidence that its condition held: `check --kind skip_step --key <step> --evidence <file>`.
- The bundle can never carry a push, a go-live, a send, a deletion or a suppression change. `propose` refuses them.
- A quote-based bypass must name the gate and be said after the bundle: `bypass-check --gate <gate> --quote "<their words>" --quoted-at <ISO time>`.

## Touchpoint 3: one reply for copy sign-off and the draft push

1. Run `scripts/check-copy-variation.py` with `--leads-file <the leads file>`. Keep the PASS report: it is the copy receipt.
2. `python3 scripts/run-approvals.py propose-signoff --run <run> --campaign-ids <ids> --fingerprint <template_fingerprint from the receipt> --leads-file <the leads file> --account <platform client id, 0 for your own account>`
3. Show the message with the review page. Record the reply.
4. Push through the wrapper only: `scripts/push-safe.py ... --signoff-run <run> --copy-receipt <receipt> --platform-client-id <id> --apply`.

The sign-off is read by the push wrapper and by nothing else. It does not open the push hook: a raw API call or a direct MCP lead push is still refused, because those skip suppression, cooldown and logging. It covers the named campaigns, the named sending account, the exact leads file, the copy as signed, and only while the campaign is DRAFTED or PAUSED. It never covers go-live.

## Touchpoint 5: the exceptions digest

When something falls outside the bundle (a spend over its cap, leads you are unsure about, a gate you believe is a false positive, a fallback rate above its limit), do not stop and ask. Run `digest-add`, carry on with the work it does not affect, and at the next natural stop send ONE message from `digest-show`.

## Before closing the run

`python3 scripts/capacity-check.py --campaign <id> ...` must pass. The hardening hook refuses a start without a fresh capacity proof, and a run is not reported as finished without it.
