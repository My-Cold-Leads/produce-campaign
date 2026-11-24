<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

## Phase 8: Push to Sending Platform

**Push through the wrapper, never with a raw API call.** This repo ships one for Smartlead: `scripts/push-safe.py` (Python 3 standard library, plus `psycopg` only if it reads your outreach log straight from Postgres). Every push path - the main run, a top-up, a one-off recovery - calls it. The push-safe hook blocks raw calls to the leads endpoint.

```bash
# 1. Dry run (the default): shows who would be pushed, who is skipped and why. Nothing is sent or logged.
#    --write-approval-request produces the file the approver signs in 7.7.
DATABASE_URL=postgres://... python3 scripts/push-safe.py \
  --campaign 12345 --client ACME --campaign-name "ACME P2 E1" --leads leads.csv \
  --template e1.html --write-approval-request approval.json

# 2. After the push approval gate (approval.json signed) and a fresh hardening proof (5.1): add --apply
SMARTLEAD_API_KEY=... DATABASE_URL=postgres://... python3 scripts/push-safe.py \
  --campaign 12345 --client ACME --campaign-name "ACME P2 E1" --leads leads.csv \
  --template e1.html --approval approval.json --apply

# No direct database access? Use JSON exports instead. File mode requires a suppression file
# and an email_status column in the lead file; --apply appends to the outreach log file.
python3 scripts/push-safe.py --campaign 12345 --client ACME --leads leads.csv \
  --outreach-log outreach_log.json --suppression suppression.txt
```

What it does, in order: drops invalid emails and repeats of the same person; applies the per-client personal-email rule if `--exclude-personal-emails` is set (2.2b); skips suppressed contacts and company domains (7.2b); skips any email status outside the allowed list (7.2); skips people with a prior positive or wrong-person reply (database mode); skips anyone inside the 90-day cooldown (`COALESCE(first_sent_date, loaded_date)`, so queued-but-unsent counts); skips leads missing a merge field the template uses; checks the signed approval (7.7); reads the campaign back and refuses if its name does not match the client or `--campaign-name`; runs the live membership check (7.3c); forces the three settings below to false on every request; posts in batches of up to 1,000; reconciles each batch against `total_leads`; writes the outreach log row for each lead as its batch is accepted; persists one state line per batch plus the full skipped list; prints `attempted / succeeded / failed / skipped` with reasons and exits non-zero on any failure. A cooldown shorter than 90 days needs `--cooldown-reason`. A client name that has no history in a non-empty outreach log is refused unless you pass `--first-push-for-client`, because a mistyped client name silently switches the cooldown off.

**Required settings on every push, from every code path (the wrapper forces these):**

```javascript
settings: {
  ignore_global_block_list: false,   // NEVER true. See below.
  ignore_unsubscribe_list: false,    // NEVER true. See below.
  ignore_duplicate_leads_in_other_campaign: false,  // your own gate is the authority
}
```

**Never switch off the block list.** These two flags bypass the platform's own suppression lists, and there is no legitimate use case for either. You will be tempted the first time a push is partially rejected. It does not even work: the platform runs its own enforcement pass afterwards and strips those leads out anyway, after some of them have been emailed. We pushed a few hundred leads this way; the platform accepted them, then stripped about two thirds within 24 hours. If you think you need this, the real fix is upstream - get the address properly removed from the block list, or mark it do-not-contact on your side and stop pushing it.

**Batching rules (built into the wrapper; keep them if you write your own):**
- Up to the platform's per-request cap per batch (Smartlead accepts up to 1,000 leads per request)
- 500ms delay between batches
- Wrap each batch so one rejected batch does not abort the push
- Report `attempted / succeeded / failed` with the failing addresses, and keep the response body on failure

**Reconcile against the right field.** Platforms report several counts and they do not mean what they look like. On Smartlead, `total_leads` is the truth, not `upload_count`. Check the actual campaign lead count via the API afterwards rather than trusting the push response.

### 8.0 - Log the outreach AT PUSH TIME (NON-NEGOTIABLE)

> **This rule was reversed in August 2026.** The original version said not to write the outreach log at push time and to let the post-send sync handle it. That was wrong.

**Write one outreach log row per lead at the moment you push**, with `loaded_date = NOW()`. Let your sync job backfill `first_sent_date` later, when the platform actually sends.

The reason is the gap. A lead pushed at 4pm may not send until the following morning. If nothing is logged until the send, then for that whole window the contact looks untouched:

- The cooldown gate does not see them, so a second push loads them again
- TAM pacing counts them as available, so your reachable-contact numbers read high and you plan against a number that is not real

Every cooldown check reads `COALESCE(first_sent_date, loaded_date)`, which is what makes both timestamps work together: the load date protects the window, the send date is the truth once it exists.

**Do this inside the push function, not as a separate step someone can forget.** `scripts/push-safe.py` writes these rows as each batch is accepted. If the push succeeded and the log write failed, that is a failure to report, not a warning to swallow.

Push per campaign in sequence. After each push:
- Verify lead count via API
- **Output 2 sample emails from the new batch** - fetch 2 leads and display the full rendered email:
  ```
  --- Sample 1: [First Name] [Last Name] <email> | [Company]
  Subject: [subject line with variables resolved]
  E1: [observation field]
  Bullets: [bullet1] / [bullet2] / [bullet3]
  Company: [company_name] | Proof: [proof_line_1] / [proof_line_2]
  E2 opener: [e2_opener]
  ```
  Show 2 samples per campaign - one with name-drop, one without (if both exist).
- Update config Campaign Roster with new lead count

### 8.1 - Mark Copy as Pushed + Audit Log (NON-NEGOTIABLE)

After successful push, update your copy version tracking:
```sql
UPDATE campaign_copy_versions
SET pushed = true, pushed_at = NOW()
WHERE client_name = $client AND campaign_id = $campaign_id
  AND pushed = false;
```

Log the push:
```sql
INSERT INTO campaign_push_log
  (client_name, campaign_id, campaign_label, action, detail)
VALUES ($client, $campaign_id, $label, 'leads_pushed',
        '{"attempted": 100, "succeeded": 98, "failed": 2, "failed_ids": ["a@example.com", "b@example.com"], "signal_types": {"expansion": 60, "generic": 38}}'::jsonb);
```

### 8.2 - Copy signal_type to Outreach Log (NON-NEGOTIABLE)

After leads are pushed, backfill `signal_type` on your outreach log from campaign variables:
```sql
UPDATE outreach_log ol
SET signal_type = cv.signal_type
FROM campaign_variables cv
JOIN contacts c ON c.id = cv.contact_id
WHERE LOWER(ol.email) = LOWER(c.email)
  AND ol.client_name = $client
  AND ol.signal_type IS NULL
  AND cv.client_name = $client
  AND cv.signal_type IS NOT NULL;
```

This ensures the outreach log always has the signal_type for quick filtering and rotation decisions.
