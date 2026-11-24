<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

## Phase 3: Email Validation

Email validation happens AFTER selecting contacts in Phase 2.

### How Email Waterfall Works

An email waterfall runs a contact through multiple finding/verification providers in sequence until a valid email is found. The concept:

1. **Finding providers** discover email addresses from a name + company domain:
   - **Prospeo** - best starting point for enrichment (finding + verification in one). Free re-enrichment, no charge on a miss.
   - **Icypeas** - good coverage for European contacts
   - **Findymail** - strong for tech/SaaS companies

   Note this is the ENRICHMENT phase - one known person, one email wanted. That is the job Prospeo is first for. For DISCOVERY (a company, wanting a list of people), Apollo's free search goes first. See Phase 0.3.

2. **Verification providers** confirm an email is deliverable before you send:
   - **MillionVerifier** - fast and cheap bulk verification
   - **BounceBan** - good catchall domain handling, confirms individual mailbox existence

3. **The waterfall pattern**: Try Provider A. If no result, try Provider B. If found, verify with a verification provider. Save the result with which provider found it (for tracking yield per tool).

If you're just starting out, **Prospeo alone** handles both finding and basic verification. Add more providers as you scale.

### 3.0 - Re-verify Stale Emails Before Campaign Assignment (HARD BLOCK)

Every contact in the cohort goes back through verification before it is assigned to a campaign if:
- its email status is blank, OR
- it was last verified **more than 3 months ago**

Mailbox status drifts with staff turnover and server changes. Within 3 months the old result is reliable; past that it is not.

**Order matters:** stage the cohort in a working list (a separate table, CSV or tag in your database, not yet assigned to any campaign) -> re-verify the stale ones -> drop anything that comes back invalid or not found -> only then write the campaign assignment -> push. Writing the assignment first means every invalid drop needs a second write, and a cleanup on the sending platform if the push already happened.

A per-client setting in your config (for example `accept_catchall: true` or `false`) controls which statuses you accept after verifying. It never skips verification. If the verifier is down, stop - do not push stale statuses.

### 3.1 - Validation Count and Cost Estimate

Before running validation, count how many contacts need it:
```sql
SELECT COUNT(*) FROM contacts c
WHERE c.client_name = '{CLIENT}'
  AND (c.email_status IS NULL
       OR c.email_searched_at IS NULL
       OR c.email_searched_at < NOW() - INTERVAL '3 months')
  AND c.kdm IN ({target_personas})
```

Estimate cost: ~$0.005/contact (single verify) or ~$0.02/contact (full waterfall with multiple providers). Report before starting.

### 3.2 - Run the Waterfall

Push contacts through your email finding/verification pipeline. Track results per provider so you can measure yield.

### 3.3 - Monitor

```sql
SELECT step, COUNT(*) FROM email_waterfall_queue
WHERE batch_id LIKE '{CLIENT}%'
GROUP BY step ORDER BY step
```

Report results: "X emails found, Y not found. Find rate: X%."

### 3.3b - Do not re-search a miss too soon

A contact the waterfall could not find an email for is a "not yet", not a "never". But re-running every provider on the same person next week costs full price for near-zero yield.

Set `not_found_until` to about 60 days out when a contact exhausts the waterfall, and exclude those from the next run. Note this is a different clock from the 90-day outreach cooldown: one governs how often you re-search for an email, the other governs how often you email a person. Do not collapse them into one number.

### 3.4 - Catchall Decision

Contacts returning `deliverable_catchall` status: include in campaigns but monitor bounce rates closely for the domain. If catchall domain bounce rate exceeds 3%, pause that domain and remove remaining catchall leads from that domain.

### 3.5 - The Email Must Belong to This Business (HARD BLOCK at load time)

A verified email can be a real inbox at the wrong company. Scraping and lookups attach addresses from unrelated businesses more often than you expect.

- **Accept** an email when its domain is the company's own domain (or shares a distinctive token with the company name), or when it is a personal or freemail address whose local part is the contact's own name.
- **Reject** it, and treat the contact as "email not found", when the domain clearly belongs to a different kind of business or institution (an estate agent, a pharmacy, a town hall, a hotel, a university, a law firm) and shares no token with the company name.

**Why:** contamination is cheap to create and expensive to reverse. Once those leads are live, re-enriching them safely recovers very few.

**How to check:** list each pushed email domain next to the company domain and name, flag rows that share no token, and review them before load.
