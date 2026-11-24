<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

## Phase 5: Campaign Infrastructure

For any new campaigns, create and configure them in your sending platform.

For existing campaigns, verify:
- Campaign IDs are correct in config
- All domains assigned are healthy (reply rate >2%, bounce rate <3%)
- All sequences loaded and correct
- One domain per campaign (hard rule - do not put two client domains on one campaign)
- Schedule is staggered (non-predictable start/end times: e.g., one starts at 08:14, another at 09:47, another at 08:31 - no round-hour starts, no matching end times)

**Sequences MUST be loaded before variable generation.** The format audit in Phase 6 reads from the live sequences.

### 5.1 - Deliverability Hardening (HARD GATE - must be green while the campaign is still a draft)

Two settings decide whether your emails look like mail or like marketing. Both must be set before the campaign sends anything:

| Setting | Required value | Why |
|---------|---------------|-----|
| Open tracking | OFF | The tracking pixel is a spam signal and inflates nothing you can act on |
| Click tracking | OFF | Rewritten links on a new domain are a strong spam signal |
| Send as plain text | ON | HTML multipart from a cold domain underperforms consistently |

**Two traps, both of which have bitten us:**

1. **Tracking is immutable once the campaign starts sending.** If you get this wrong, you cannot fix it on that campaign - you rebuild it. So this must be verified at draft time, not after launch.
2. **Saving any other campaign setting silently resets plain text to off.** Renaming a campaign un-hardens it, with no error and no warning. So this is not a set-once step: **re-verify after every settings change, and immediately before launch.**

**Verify by reading the campaign back from the API, not by remembering that you set it.** Assert the exact expected values and fail on anything unexpected. An audit found roughly a third of our campaigns un-hardened, almost all from trap 2.

If you set both in one call, set tracking first and plain text second. The reverse order errors on some platforms.

**Record the proof with the verifier, not by hand.** The read-back is a script:

```bash
SMARTLEAD_API_KEY=... python3 scripts/verify-hardening.py --campaign <campaign_id> --follow-up-percent <agreed value>
```

It reads the campaign from the API (read-only), checks the settings below, and only then writes `.claude/campaign-state/hardening-<campaign_id>.ok`. If any check fails it writes nothing and deletes an older proof for that campaign.

The deliverability hook (`pretooluse-deliverability-hardening.sh`) refuses any activation, lead push or `push-safe.py --apply`, from the shell or through an MCP tool, unless a proof for **that exact campaign** exists and is newer than `HARDENING_MAX_AGE_MIN` minutes (default 120). A proof for one campaign never unlocks another, and an empty file made with `touch` is not a proof. It goes stale on purpose: re-run the verifier after any settings change and immediately before launch.

**Two more settings the verifier checks:**

- **The gap between emails belongs on each inbox, never on the campaign.** Set the wait time per sending inbox and leave the campaign-level "time between emails" at the platform minimum. A campaign-level gap overrides every inbox on that campaign and quietly cuts volume below what the inboxes can send. If you change an inbox gap on a campaign that is already active, pause and resume the campaign (with the user's OK) so the platform rebuilds its send plan.
- **Follow-up percentage is agreed per client and per number of emails in the sequence.** It decides how much daily capacity goes to follow-ups versus first emails, and the right value differs for a 2-email and a 3-email sequence. Store the agreed values in the client config (section 14 of `setup/campaign-config.template.md`), set it as the LAST settings change (a save in the platform UI can overwrite it), and pass it to the verifier. A sequence length with no agreed value means ask the user; never leave the platform default in place by accident.

### 5.1b - Send-Set Receipts Before Launch (HARD GATE, instruction-only)

Two checks on the exact set of leads that can still send, run after the push and before the launch gate. Each produces a small receipt file (what was checked, counts, failures, time) that you cite at the launch gate. No receipt, no launch.

1. **DNS receipt.** For every recipient domain in the send set, confirm it has an MX record now. Verification statuses age; a domain that has lost its MX since verification is a guaranteed bounce. Lookups time out at random, so re-run the unresolved ones rather than passing or failing them. Zero no-MX addresses may remain.
2. **Link receipt.** Extract every URL from the rendered emails and signatures. Each one must be on a domain the client approved for this campaign, must resolve, and must not be a tracking or redirect link (click tracking is off for a reason; a rewritten link brings the spam signal straight back). Also confirm no email names a different company than the lead's own.

### 5.2 - Sequence Structure Lock (HARD BLOCK before push)

Declare the sequence structure early, once personas and ICP are locked and before any E2/E3 generation. Write it to a small lock file per campaign:

- Number of steps
- Per step: subject pattern, delay in days, minimum body length

For example `sequence-lock.json` next to the campaign's other files:

```json
{
  "campaign": "acme-2026-09-p1",
  "steps": [
    {"step": 1, "subject": "{pregunta|duda} sobre {{company}}", "delay_days": 0, "min_body_words": 60},
    {"step": 2, "subject": "", "delay_days": 3, "min_body_words": 40},
    {"step": 3, "subject": "", "delay_days": 4, "min_body_words": 25}
  ]
}
```
An empty subject means the step replies in the same thread.

**Before push, read the live sequences back from the platform and compare them to the lock.** Fail loudly on any mismatch in step count, subject, delay or body length.

**Why:** a campaign can go live with an empty or missing follow-up step, and nothing in the variables will show it. The lock checks the live platform, independent of whatever else ran.

**Recovery:** if a step is missing mid-cycle, copy it from the most recent active campaign for the same persona, never from an archived copy that may carry empty steps.
