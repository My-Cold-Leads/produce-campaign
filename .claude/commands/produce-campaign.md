---
name: produce-campaign
description: End-to-end pipeline for generating personalized cold email variables, validating quality, and pushing to your sending platform. Config-first approach that survives context window resets. Use when producing campaign variables, loading leads, generating E1/E2 variables, or when the user says "produce campaign", "run production", "generate campaign variables", "load campaign leads", or "campaign production".
---

# Produce Campaign

End-to-end pipeline from session setup through launch. Reads all configuration from the client config - no hard-coded values. Every step has a gate; skipping any step requires explicit approval.

> **Note:** This skill was built for Spanish-language B2B cold email campaigns but is adaptable to any language. Spanish examples are used throughout - substitute your target language as needed.
>
> **Scope:** email only. The cooldowns, the per-company recipient cap and the sequence structure all assume a receiving mail server. If you add another channel, decide it before Phase 1, because nearly every phase branches on it.

---

## The five rules underneath everything else

If you remember nothing else from this document, remember these. Every gate below is one of them applied to a specific step.

1. **Never let the AI invent.** Give every generation step a sanctioned way to say "I don't know", and make that the preferred answer. Prohibition alone does not work - the model's default is to produce something.
2. **Never lose work you paid for.** Write each result the moment it exists. Wrap every row so one bad row costs one row.
3. **Never trust a field in isolation.** What the lead receives is the template plus the values plus the spintax, rendered together. Bugs live in the seams.
4. **Never report your own filter as a ceiling.** Re-derive availability from the universe using hard constraints only, and show the whole funnel.
5. **Never treat a green check as proof.** A validator that has never gone red on known-bad input might be working, or might be silently passing everything. Build the failing input first.

**Client:** Parse from $ARGUMENTS, or ask if not provided.

---

## MANDATORY STEP ENFORCEMENT (NON-NEGOTIABLE)

**Claude MUST NOT skip any phase without the user saying "skip [phase name]" explicitly.** If a phase seems unnecessary (e.g., "we just refreshed the data"), still run the check, confirm it's clean, report the result, then move on. The overhead of checking is seconds; the cost of skipping and being wrong is hours.

After completing each phase, state:
> "Phase [N] complete. [One-line result]. Moving to Phase [N+1]: [what it does]. Proceed?"

Do not proceed to the next phase until the user says yes (or the phases are clearly sequential within an approved workflow).

---

## Phase 0: TAM Creation (First-Time Setup)

**Skip this phase if you already have companies and contacts in your database.**

This skill is focused on campaign production - taking a list of companies and contacts through to a launched, quality-checked campaign. It's not a deep-dive on TAM strategy or list building (we have a whole separate process for that). But you need a solid list before any of the other phases work, so here's a quick version to get you started.

### 0.1 - Define Your ICP

Before sourcing companies, define who you're targeting:
- **Industry/sector** - what types of companies? (e.g., accounting firms, logistics, SaaS, hotels, law firms, manufacturing)
- **Company size** - employee count range? (e.g., 50-500 employees)
- **Geography** - which countries, regions, or cities?
- **Key decision makers (KDMs)** - who are you emailing? (e.g., CEO, Head of Finance, Operations Director)
- **Exclusions** - who do you NOT want? (e.g., companies under 10 employees, government agencies)

Document this in your client config file. Every sourcing decision flows from the ICP.

**If you are qualifying companies against the ICP with a model rather than by
hand, iterate that prompt properly before you run it.** ICP qualification is a
classifier, and a classifier that is 85% right silently poisons every phase after
it - you enrich, research and write to companies that were never a fit, and you
pay for all of it. See [iterative-prompting.md](iterative-prompting.md): one
anchor, rounds of 10 fresh samples, lock on two consecutive zero-edit rounds, then
walk the sample-size ladder before the full batch.

### 0.2 - Source Companies

Use one or more of these tools to build your company list:

| Source | Best for | How to use |
|--------|----------|-----------|
| **Apollo** | B2B companies with employee filters, industry, location | Search with your ICP filters, export company list as CSV |
| **Prospeo** | Finding companies by domain or LinkedIn | Company search + enrichment |
| **Google Maps / local directories** | Local businesses (restaurants, shops, workshops) | Search by category + location, extract business websites |
| **LinkedIn Sales Navigator** | Targeted account lists with advanced filters | Build account list, export |
| **Industry directories** | Niche markets with specialized directories | Scrape or manually collect |
| **Your existing network** | Warm leads, referrals, past clients | Export from CRM |

**After sourcing, save ALL companies to your database immediately:**
```sql
INSERT INTO companies (client_name, domain, company_name, sector, city, country)
VALUES ('{CLIENT}', 'company.com', 'Company Name', 'logistics', 'Lisbon', 'Portugal')
ON CONFLICT (client_name, domain) DO NOTHING;
```

Aim for 3-5x more companies than you need for your first campaign. You'll lose some at every step (no contacts found, invalid emails, DNC'd, etc.).

### 0.3 - Find Contacts at Those Companies

For each company, find the decision makers matching your KDM personas.

**Discovery and enrichment are different jobs. Run them in this order or you will overpay by roughly 4x.**

| Phase | You have | You want | Tool | Why this order |
|-------|----------|----------|------|----------------|
| **1. Discovery** | A company | A list of people at it | **Apollo first.** Its people search is free. | Paid search tools charge per result page whether or not you already hold that person. |
| **2. Dedupe** | Search results | Only the people you don't have | Your own database | This is the step that saves the money. Fuzzy match on first name + title + company domain. |
| **3. Enrichment** | A named person with no email | Their verified email | **Prospeo first**, then Apollo bulk match, then Icypeas or Findymail | Prospeo has free re-enrichment and does not charge on a miss, so it amortises cheaper at the same headline credit cost. |

Other sources: LinkedIn Sales Navigator for specific people by title, and company team/about pages, which are free and often list leadership.

**The incident behind this:** running a paid search-first tool in the discovery slot cost us roughly 4x what it should have, because most of the spend went on people already in our database.

**90-day cohort cooldown.** Do not re-run discovery over the same company list within 90 days. It returns about 5% new finds at full cost. Record the date you last ran discovery per company (`last_ai_contact_search_date`) and filter on it.

**A person found without an email is still a find.** Save the contact with a null email and send it to the waterfall in Phase 3. Discarding it means paying to discover them again next quarter.

**Save ALL contacts to your database:**
```sql
INSERT INTO contacts (client_name, email, first_name, last_name, job_title, company_domain, kdm)
VALUES ('{CLIENT}', 'maria@company.com', 'Maria', 'Garcia', 'Head of Operations', 'company.com', 'P1')
ON CONFLICT DO NOTHING;
```

**Assign KDM personas** (P1, P2, P3, etc.) based on job title and seniority. P1 = your primary decision maker, P2 = secondary, etc. Define what each persona means for YOUR ICP in the client config.

### 0.4 - Verify Emails

Contacts without verified emails cannot be pushed to campaigns. See Phase 3 for the full email validation process.

At minimum, run all found emails through a verification service (Prospeo, MillionVerifier, or BounceBan) and update the `email_status` field. Only `valid` and `deliverable_catchall` emails proceed.

### 0.5 - TAM Health Check

After sourcing, check your numbers:
```
Companies sourced: X
Contacts found: X (X% of companies have at least one contact)
Emails verified: X valid + X catchall = X contactable
Coverage: X contactable / X companies = X%
```

If contactable coverage is below 40%, go back and try additional sources before proceeding. The pipeline needs volume to work - a campaign with 50 contacts won't give you meaningful data.

---

## Phase 1: Session Setup

### 1.1 - Load Client Config

Read your client config: one file per client, built from [`setup/campaign-config.template.md`](../../setup/campaign-config.template.md), plus that client's prompts from your prompt library.

If no config exists, copy the template and fill in every section before proceeding. Keep it wherever you keep client files; tell the skill where it is.

Verify:
- All lookup tables present (every persona x every sector)
- Every prompt this run needs exists in your prompt library (or your `prompts/` directory)
- Campaign IDs set for any existing campaigns
- INDUSTRY_MAP covers all sectors in your database

State: "Loaded {CLIENT} config. Last updated: {date}. Status: {summary from Status & Next Move}."

### 1.1b - Client Peculiarities Check (MANDATORY)

If you maintain a client-specific rules file, read it and apply all rules before proceeding. These override the generic pipeline. They exist because of real incidents.

State: "Loaded peculiarities for {CLIENT}: [one-line summary of the rules that apply to this push]."

### 1.1b2 - Production Incidents Review (MANDATORY)

If you maintain a production incidents log, review it. Check if any past incidents are relevant to this client or this type of production run. Apply any lessons learned.

If 3+ incidents share the same root cause area and no fix has been applied yet, STOP and patch the pipeline before proceeding.

State: "Reviewed {N} past incidents. {relevant count} relevant to this run: [one-line each]." or "No relevant past incidents."

### 1.1c - Client-Level Production Scripts (MANDATORY)

Check the "Client scripts" section of your client config for client-specific production scripts that must run as part of every campaign push.

If any exist, list them and ask the user which to run before proceeding. These are client-specific automation scripts that encode logic not captured in the generic pipeline (domain caps, persona routing, custom field logic, etc.).

**Do not skip this check.** A missed client script means wrong leads, wrong fields, or uncapped domains.

State: "Found {N} client scripts for {CLIENT}: [list]. Run these? Or are we doing manual production?"

### 1.2 - TAM Pacing Check (MANDATORY every session)

Run EVERY time, even re-runs and quick pushes. You need to see TAM health in every session.

**ONE COOLDOWN: 90 DAYS.** It is the same number in the pacing query, the selection query and the pre-push gate. If you find a different number anywhere in your pipeline, that is a bug, not a variant. A shorter cooldown is a documented per-client exception, never a default.

**The cooldown reads `COALESCE(first_sent_date, loaded_date)`**, so a lead that is queued but not yet sent still counts as contacted. Reading `first_sent_date` alone lets the same person be loaded twice inside the window between push and send.

```sql
SELECT
  COUNT(*) FILTER (WHERE email_status IN ('valid','deliverable_catchall')) as total_contactable,
  COUNT(*) FILTER (WHERE email_status IN ('valid','deliverable_catchall')
    AND NOT EXISTS (SELECT 1 FROM outreach_log ol
      WHERE ol.contact_id = c.id AND ol.client_name = '{CLIENT}'
      AND COALESCE(ol.first_sent_date, ol.loaded_date) > NOW() - INTERVAL '90 days')) as eligible_now,
  COUNT(*) FILTER (WHERE email_status IN ('valid','deliverable_catchall')
    AND NOT EXISTS (SELECT 1 FROM outreach_log ol
      WHERE ol.contact_id = c.id AND ol.client_name = '{CLIENT}'
    )) as never_contacted,
  COUNT(*) FILTER (WHERE email_status IN ('valid','deliverable_catchall')
    AND EXISTS (SELECT 1 FROM outreach_log ol
      WHERE ol.contact_id = c.id AND ol.client_name = '{CLIENT}'
      AND COALESCE(ol.first_sent_date, ol.loaded_date) > NOW() - INTERVAL '90 days')) as in_cooldown
FROM contacts c
LEFT JOIN companies comp ON comp.domain = SPLIT_PART(c.email, '@', 2)
  AND comp.client_name = '{CLIENT}'
WHERE c.client_name = '{CLIENT}'
  AND (c.do_not_contact IS NULL OR c.do_not_contact = false)
  AND (comp.do_not_contact IS NULL OR comp.do_not_contact = false)
```

**Contactable email_status values: `'valid'` and `'deliverable_catchall'` ONLY. NOT `'catchall'`.**

### 1.2b - A filter you applied yourself is not a ceiling (NON-NEGOTIABLE)

**Before reporting any number as a cap, a max, or "all we have", re-derive it from the whole universe using HARD constraints only.**

Hard constraints are the ones you cannot reverse today: do-not-contact, no contact method at all, an active cooldown, wrong geography. Everything else is soft, and soft-excluded rows are still available:

| Soft (recoverable, report it) | Why people mistake it for hard |
|---|---|
| A size cap or sample you imposed | It produced the list you are looking at |
| Weighting or prioritisation | The deprioritised rows silently vanished |
| Membership of a staging table | The staging table feels like the universe |
| An unvalidated dedup key | Legitimate identity dedup is hard, but a mis-normalised key that false-matches is soft |
| A step status like waterfall `step = 'done'` | It is an artifact of your process, not of the contact |
| `email IS NULL` | That means no email **yet**, not no email findable |

Always present the funnel, not the endpoint:

```
universe -> hard-excluded -> available -> selected -> recoverable
```

**Trip-wire, when you catch yourself about to report a ceiling:** "that is the count after my own filter. Let me run the hard-constraints-only universe first."

We once reported a persona as capped at a few hundred contacts when several times that were available, and every one of them was contactable. Same root cause as an earlier "0 already in the database" that turned out to be a broken dedup key.

Report format:
```
TAM PACING - {CLIENT}
Total contactable: X (valid + catchall)
Eligible now: X (not in 90-day cooldown)
  - Never contacted: X
  - Previously contacted, now eligible: X
In active cooldown: X (contacted within 90 days)

At {N} contacts/push x {frequency}/month = {X} contacts/month
TAM capacity: {total_contactable} / 3 pushes/year ~= {X}/push
```

**Surge vs steady-state decision:**

| Available pool | Action |
|----------------|--------|
| > 1,000 | Can surge above monthly target for critical months |
| 500-1,000 | Caution - dial back toward steady state |
| < 500 | Lock to steady state. Source new contacts before next push. |

Available pool = `never_contacted + (contacted > cooldown_period ago)`. The monthly target is the rate that keeps the pool sustainable long-term. Surges are valid tactics but must be offset by new sourcing when pool drops.

### 1.3 - AI Contact Discovery Freshness (MANDATORY - check at EVERY session start)

Before doing any contact work, check when AI discovery was last run per company. Stale discovery means missed decision-makers.

```sql
SELECT
  COUNT(*) FILTER (WHERE comp.last_ai_contact_search_date > NOW() - INTERVAL '3 months') as fresh,
  COUNT(*) FILTER (WHERE comp.last_ai_contact_search_date <= NOW() - INTERVAL '3 months'
    OR comp.last_ai_contact_search_date IS NULL) as needs_discovery
FROM companies comp
WHERE comp.client_name = '{CLIENT}';
```

If `needs_discovery > 0`: flag this. New discovery goes through the full waterfall before being campaign-eligible. Schedule but don't block current push if there are enough eligible contacts.

### 1.4 - Copy Reuse and Structure Rotation Check

**Default: reuse the live approved copy.** Each new monthly cohort starts from the copy that is live and approved right now, pulled from your sending platform. Copy only changes when someone approves a specific change. Age alone is not a reason to rewrite winning copy.

**Structure rotation is a separate, deliberate axis (ESP fatigue).** Mailbox providers fingerprint structure, not just words, so per-lead AI variation does not stop it. Rotate structure on a schedule even while the wording stays approved:

| Layer | What to rotate | Cadence |
|-------|----------------|---------|
| E1 wrapper structure | Paragraph count, proof anchors, close phrasing | Every 6-8 weeks |
| E2 format | Alternate between a bulleted list and 3 sentences of prose | Every 6-8 weeks |
| Subject lines, signature, unsubscribe wording | Variation across the cohort (see 7.1) | Continuous |

Pull `updated_at` from each active campaign's sequences. If the wrapper structure has run for 6-8 weeks, flag it:
> "The E1 wrapper for [campaign] has run since [date] - [X weeks]. Structure rotation is due. The approved wording carries over."

**Rotate early when reply rate drops more than 30% week over week with a stable bounce rate.** That shape is fingerprint fatigue, not a list problem. Record which wrapper variant each cohort ran so the next cycle knows what to rotate away from.

Domain rotation helps but does not replace wrapper rotation. You need both.

**When a rotation or a copy change is due:**
1. Identify which E1 variant and wrapper are currently running
2. Suggest 2-3 alternative structures that suit the client's offer and persona
3. Present the options to the user before writing any new copy

### 1.5 - 4-Month Cycle Tasks

Check these three tasks. They run together once per 4-month cycle:

**Company research refresh:**
```sql
SELECT COUNT(*) FILTER (WHERE comp.updated_at < NOW() - INTERVAL '4 months' OR comp.updated_at IS NULL) as needs_research
FROM contacts c
JOIN companies comp ON comp.domain = SPLIT_PART(c.email, '@', 2) AND comp.client_name = '{CLIENT}'
WHERE c.client_name = '{CLIENT}' AND c.email_status IN ('valid','deliverable_catchall')
  AND NOT EXISTS (SELECT 1 FROM outreach_log ol WHERE ol.contact_id = c.id AND ol.client_name = '{CLIENT}' AND COALESCE(ol.first_sent_date, ol.loaded_date) > NOW() - INTERVAL '90 days')
```

**AI contact search refresh:** See 1.3 above.

**New contact waterfall:** After discovery, enqueue new contacts through email finding (see Phase 3).

Flag if any are overdue. These can run in parallel with the current push if there are enough current eligible contacts.

### 1.5b - Reuse Durable Company Facts (NON-NEGOTIABLE)

Most company data does not change between campaigns. Read it back from your database; regenerate only what goes stale.

| Company data | Treatment |
|--------------|-----------|
| Normalized name | **Reuse.** Generate only for empty rows. |
| Homepage text | **Reuse.** Re-scrape only if empty or on a deliberate refresh. |
| What they make, operations, sites, firmographics | **Reuse.** Research only when missing. |
| Sales signals (recent news, expansion, investment, mergers) | **Fresh every campaign.** Re-query the sources, never re-summarise an old result. |
| Person signals (job change, promotion) | **Fresh every campaign.** |

**Generate only the fields the live template uses.** Read the live sequence templates first and generate only the `{{variables}}` they contain. Every unused field is a paid call for copy that reaches no inbox. Unused fields already sitting on leads are harmless - never scrub them and never let a gate fail on them.

**Why:** re-generating durable facts every month costs money and can quietly change a company name or fact that was already approved.

**How to check:** before any durable-fact generator runs, confirm it only selects rows where that field is empty. A bulk overwrite of a populated durable field needs an explicit refresh decision.

### 1.5c - Stage Coverage Check (HARD BLOCK before generation and push)

A script that reports "done" can still have skipped part of the cohort. Prove each enrichment stage reached its target on this cohort, not on the whole table:

| Stage | Target |
|-------|--------|
| Company research (operations / what they make) | 95%+ of cohort companies processed |
| Signal classification | 95%+ processed |
| Person signals | 95%+ of eligible contacts processed |
| Final E1 body (or equivalent) | 100% of eligible contacts |

Count eligible, processed and hit per stage against the cohort list and fail loudly below target.

**Every stage must be safe to re-run for just the gaps.** A re-run selects only rows where the field is missing and never re-processes finished rows. The fix for a failed stage is to re-run that same stage, not to write a one-off patch script.

**Why:** a stage once reported success while silently missing about 7% of the cohort through a pagination edge case. Only a per-stage count against the cohort caught it.

---

## Phase 2: Contact Selection

### 2.1 - Persona Assignment

The persona for each contact is stored in your contacts table (e.g., `contacts.kdm`) - set by the KDM classifier during import. **DO NOT re-classify from job title.** Read the `kdm` field directly.

Adapt this persona table to your client's ICP:

| kdm | Persona | Notes |
|-----|---------|-------|
| P1 | Primary Decision Maker (e.g., CEO / Managing Director) | |
| P2 | Secondary Decision Maker (e.g., VP Operations) | |
| P3 | Tertiary Decision Maker (e.g., Operations Director) | |
| P4 | Influencer (e.g., Department Manager) | |
| P5 | Finance Decision Maker (e.g., CFO) | |
| P0 | Out of ICP | **Do NOT push to any campaign** |
| null | No KDM set | Skip - investigate before pushing |

### 2.2 - Quality Filters

For each persona, query eligible contacts:

```sql
SELECT
  c.id,
  c.email,
  c.first_name,
  c.last_name,
  c.job_title,
  c.kdm,
  SPLIT_PART(c.email, '@', 2) as domain,
  COALESCE(comp.normalized_name, INITCAP(LOWER(comp.company_name)), comp.domain) as company_display
FROM contacts c
LEFT JOIN companies comp ON comp.domain = SPLIT_PART(c.email, '@', 2)
  AND comp.client_name = '{CLIENT}'
WHERE c.client_name = '{CLIENT}'
  AND c.email_status IN ('valid', 'deliverable_catchall')
  AND c.kdm = '{PERSONA}'
  AND (c.do_not_contact IS NULL OR c.do_not_contact = false)
  AND (comp.do_not_contact IS NULL OR comp.do_not_contact = false)
  AND NOT EXISTS (
    SELECT 1 FROM outreach_log ol
    WHERE ol.contact_id = c.id
      AND ol.client_name = '{CLIENT}'
      AND COALESCE(ol.first_sent_date, ol.loaded_date) > NOW() - INTERVAL '90 days'
  )
  AND NOT EXISTS (
    SELECT 1 FROM campaign_responses cr
    WHERE cr.lead_email = c.email
      AND cr.campaign_id IN ({active_campaign_ids})
  )
ORDER BY c.created_at ASC
LIMIT {N}
```

### 2.3 - Company Lookup (domain join - ALWAYS use this)

Foreign key fields between contacts and companies are frequently NULL. ALWAYS join via email domain:

```sql
LEFT JOIN companies comp ON comp.domain = SPLIT_PART(c.email, '@', 2)
  AND comp.client_name = '{CLIENT}'
```

Use FK as fallback/verification only. If FK-based count and domain-based count differ, domain count is correct.

### 2.4 - In-Flight Check

Before selecting contacts, check for contacts currently in an active campaign sequence (not yet finished):

```sql
SELECT DISTINCT cr.lead_email
FROM campaign_responses cr
WHERE cr.campaign_id IN ({active_campaign_ids})
  AND cr.sequence_completed = false
```

Exclude these from selection. A contact can only be in one active sequence at a time.

### 2.5 - No-Domain Contacts

Flag any contacts where the email domain has no matching company in your companies table. These contacts will have no research data and cannot have variables generated. Either:
- Fix the company linkage first
- Or exclude them from this push

### 2.6 - Per-Company Recipient Cap (SCOPED - do not apply this as a blanket rule)

Emailing several decision makers at one company is normal and often desirable. **Do not cap it by default.** A blanket cap of one per company throws away most of your reachable TAM for no benefit.

Cap only where the receiving mail server is shared at scale:
- Large enterprises and multinationals
- Any push that would land more than roughly 5-10 addresses at one email domain in the same sending window

More than a dozen contacts at a single multinational tripped that company's inbound throttling and hurt delivery for the whole cohort. That is the failure this exists to prevent, and it does not happen at a 30-person business.

**Person-level dedup always applies** - the same individual never appears twice, in any cohort, ever.

This constraint comes from the receiving mail server, so it is specific to email.

### 2.7 - Score the List Before You Spend on It (cheap, do it every run)

Scoring and persona assignment are both language judgements, so the same rule
applies: iterate the prompt on fresh samples and lock it before you score a whole
cohort with it. See [iterative-prompting.md](iterative-prompting.md). Judging a
scoring run by its aggregate distribution is not judging it at all - check
individual rows against labels you set yourself.

Research and generation cost money per record. Scoring the list costs nothing and tells you whether it is worth spending on. Run before Phase 4.

Two dimensions catch most scraped-source damage:

| Check | Flag when | Why it matters |
|-------|-----------|----------------|
| **Bad-title density** | Interns, students, "assistant to", retired, freelance consultants above ~10% of the list | You are about to write decision-maker copy for people who are not decision makers |
| **Role-address density** | `info@`, `hello@`, `ventas@`, `contact@` above ~15% of the list | Role addresses reach a shared inbox. Personalized copy addressed to a named person lands wrong, and these bounce and complain at a higher rate. |

Also worth a look: how many companies contribute more than 3 contacts (concentration), and how many contacts share a domain with no matching company row.

If either headline number is over threshold, fix the list before spending on research. This is the cheapest gate in the pipeline.

### 2.8 - Salvage Before Drop (NON-NEGOTIABLE)

**No target gets filtered out on a single thin-input judgement.**

Every drop in this pipeline - out of ICP, wrong domain, no research found, dedup match, invalid email, out of TAM - is a decision made by one method on one pass of the data. Before any drop is final:

1. **Diagnose why it was dropped.** "Scored ICP_MISS" is not a reason, it is a label. Was the input thin? Was the domain wrong? Was the judgement made on a lossy summary rather than the full page?
2. **Re-assess on better input, with a different or deeper method than the first pass.** Re-judging a borderline miss against the full homepage catches what a judgement against a 200-character summary could not.
3. **Only the residue that survives salvage is dropped.**
4. **Report the recovery funnel**, not just the drop count:

```
dropped -> salvageable -> re-assessed -> recovered -> confirmed drop
```

"Expensive or slow to check" is not a reason to drop a target unassessed. Do the cheap version of the check, or ask.

A first ICP pass once marked several hundred companies as out of ICP based on a lossy summary. Nearly all of them came back when re-judged against their actual homepage.

---

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

---

## Phase 4: Company Data Prep

### 4.1 - Company Name Normalization (HARD GATE - do not proceed without this)

**Skipping this causes raw domains like "acmelogistics.com" to appear in subject lines.**

**Step 1: Check what already exists**
```sql
SELECT
  COUNT(*) as total,
  COUNT(comp.normalized_name) as has_norm
FROM companies comp
WHERE comp.client_name = '{CLIENT}';
```

**Step 2: GPT-4o-mini for remaining gaps only**
- **Reuse first.** If a company already has a stored normalized name, use it. Generate only for rows where it is empty (see 1.5b).
- **MANDATORY: Check your prompt library for an approved normalization prompt first.** Only write a new one if none exists.
- Test on 20 diverse examples, confirm 98%+ accuracy, save to your prompt library before running full batch.
- Batch 50 at a time. Cost: ~$0.02/1,000 companies.
- **This step MUST run before pushing leads.** If the `company_name` field on your leads still matches the raw name in your database, normalization was skipped - go back and run it.

**Normalization rules:**
- **Strip legal suffixes and place qualifiers:** S.L., S.L.U., S.A., S.A.S., Ltd, Plc, GmbH, Inc, LLC, and trailing country or region tags like "(Chile)" or "Europe". "Acme Industries S.L." becomes "Acme Industries".
- **Title Case**, with connectors lowercase (de, del, y, la, of, and) and Spanish accents restored.
- **Never invent an initialism.** A short form is allowed only when those exact letters already appear as a token in the source name. "Contenedores Ejemplo del Sur S.A." becomes "Contenedores Ejemplo del Sur", never "CES". "ACME Iberia S.L." may become "ACME", because the token is in the source. Being a real, well-known acronym is not the test - the test has to be mechanical, because "is this a real brand acronym" is the judgement a model gets wrong at scale.

**Why:** the normalized name lands in subject lines. An initialism the company never uses reads as a label for somebody else.

**How to check:** for every output made only of capital letters, confirm that exact token appears in the source name. Any row that fails is an invented initialism - fix it before push.

**Step 3: Verify - zero tolerance for domain-as-name**
```sql
SELECT comp.domain, comp.normalized_name
FROM companies comp
WHERE comp.client_name = '{CLIENT}'
  AND comp.normalized_name IS NOT NULL
  AND comp.normalized_name ~ '\.[a-z]{2,4}$'
  AND comp.normalized_name NOT LIKE '% %';
-- Must return 0 rows
```

**ALWAYS use this fallback chain in generation queries:**
```sql
COALESCE(comp.normalized_name, INITCAP(LOWER(comp.company_name)), comp.domain) as normalized_name
```

### 4.2 - Company Research (SEPARATE AGENT - NON-NEGOTIABLE)

**Research and generation are ALWAYS separate steps. NEVER use one AI call to both research AND generate variables. If research fails, re-run research only. If generation fails, re-run generation only with cached research.**

**Step 1: Check your prompt library for research queries.** Use approved search query templates. Do not write new ones without checking.

**Step 2: Choose research method**

| Method | When to use | Cost |
|--------|------------|------|
| Serper (preferred) | Default. 3 queries/domain: triggers, growth, operations | ~$0.003/domain |
| Agent reads the site directly | When you need to understand the company, not just collect snippets | ~$0.005/domain |
| Hybrid | Serper for signals, direct read for context | ~$0.006/domain |

**Let the agent doing the reasoning do its own fetching (NON-NEGOTIABLE).**

Do not pre-fetch pages with a script, convert them to text, and hand the text to a model. That pipeline strips exactly the signals a reasoning model needs: that this is a cookie wall rather than a homepage, that this is the German parent rather than the Spanish subsidiary, that this domain is parked, that the page is in the wrong language for your campaign.

Give the agent a fetch tool and a fallback ladder, and let it decide when a fetch failed:

```
native fetch -> a text-extraction proxy -> a headless browser -> flag as scrape-failed
```

A scrape-failed company is not a company you guess about. It goes to the floor template.

**Source-gating (NON-NEGOTIABLE).** Every fact that reaches a generated field must carry:
- `source_url` - the page it came from
- `source_quote` - the sentence on that page that proves it

Verify the quote with a substring check against the fetched text. A model can invent a quote as easily as it can invent a fact, so an unverified quote buys you nothing.

**If a fact is not quotable from the source, it does not go in the email.** Never infer from the industry code, the sector, the company name, or what companies like this usually do. Downgrade to the safer template instead.

**The incident behind this:** a pre-fetch-then-summarise pipeline produced wrong observations for roughly 15% of one month's cohort, because the summarising prompt was working from thin text and filled the gaps by inferring from the industry classification. Recipients replied to say we had described equipment they did not have.

**Step 3: Structured signal extraction**

For each company, extract:
- `employees` (int)
- `signals` (array) - the same values as `signal_type` in 6.8, for example: expansion, hiring, leadership_change, merger_acquisition, partnership, product_launch, award, regulatory
- `locations` (array)
- `raw` (object) - full text per query type

**CRITICAL - Operations field generation (NON-NEGOTIABLE):**

When writing the `operations` field for a company, ALWAYS include the company's known address and industry classification as ground-truth anchors in the prompt:

```
Company: {company_name}
Known address: {address} {city}
Industry: {industry_description}

Based on the search results below, describe this company's operations in 2-3 sentences.
ONLY include information consistent with the known address and industry above.
If any search result describes a different city or a different industry, IGNORE IT - it is about a different company.
```

After generating `operations`, run this validation before saving:
1. Extract any city/location mentioned in the generated text
2. Cross-check against the company's known address in your database
3. If the generated text mentions a city that contradicts the known address: DISCARD and regenerate with stricter prompt
4. If the industry doesn't match the operations described: DISCARD - wrong company data in search results

**Why this matters:** In production, a manufacturer had operations generated from a different company's search results. The lead replied to say the description was wrong. Address anchoring would have caught this immediately.

**Step 4: Save cache**

Save to a local cache file keyed by domain. Checkpoint every 50 companies.

**Report AI cost after research completes.**

### 4.3 - Persist Research to Database (NON-NEGOTIABLE)

**Research data is expensive (SERP calls, API lookups, GPT analysis). It MUST be saved to your database immediately - not just to local files. Local files die with context resets. Your database survives forever.**

After research completes for each batch, write results back to your companies table:

```sql
UPDATE companies
SET
  personalization_data = $signals_json::jsonb,
  updated_at = NOW()
WHERE domain = $domain AND client_name = '{CLIENT}'
  AND (personalization_data IS NULL OR personalization_data = '{}'::jsonb);
```

**Structure for personalization_data:**
```json
{
  "employees": 150,
  "signals": ["expansion", "partnership"],
  "locations": ["Madrid", "Barcelona"],
  "raw": { "serper_triggers": "...", "serper_growth": "..." },
  "researched_at": "2026-03-22",
  "research_model": "gpt-4o-mini"
}
```

**Write each company's result the moment it exists, not at the end of the batch.**

This is the single most expensive lesson in this document. A three-hour research run held thousands of finished results in memory, wrote them at the end in one transaction, and lost about 40% of them to a single rejected request. Every one had been paid for.

The pattern:

```python
for company in companies:
    result = research(company)          # costs money
    try:
        persist(result)                 # write it NOW, one row
        succeeded.append(company.domain)
    except Exception as e:
        failed.append((company.domain, str(e)[:500]))   # keep the BODY, not just the code
        continue                        # one bad row costs one row
```

Three rules, all non-negotiable:

1. **Persist per record.** Not per batch, not at the end of the phase. If the process dies at minute 170 of 180, you keep 170 minutes of work.
2. **Wrap every row.** An unguarded loop turns one bad row into a lost run.
3. **Report `attempted / succeeded / failed`** with the failing identifiers, never a single number. And read the error body: "409: Conflict" with the response discarded is undiagnosable an hour later.

A local cache file is a convenience, not persistence. It gets cleaned, it does not survive a new machine, and nobody else can query it.

**This step runs IMMEDIATELY after research, BEFORE moving to Phase 5.** This phase MUST complete and save before Phase 5 begins. No exceptions.

### 4.4 - ICP Check Guardrails (HARD GATE after research)

If you run an AI classifier to confirm each company fits the ICP, treat it as a **default-accept negative filter**. Every company already passed your industry filter, so exclude only companies the page proves are a non-fit.

**Classes:**
- `ICP_FIT` - fits
- `SUBSIDIARY_OF_FIT` - a local operating subsidiary of a larger group, where the local company fits even if the website is the parent's. Without this class, subsidiaries get dropped whenever their domain resolves to a parent that does not operate in your country.
- `ICP_MISS` - a proven non-fit
- `ICP_UNCLEAR` - almost never; kept, not dropped

**Writing "default-accept" in the prompt does not produce default-accept.** A small model reads a homepage that does not mention a factory and writes "no evidence", which is exactly the inference you forbade. Enforce the posture in code:

1. **A MISS needs a reason from a fixed list** (for example: law/tax/accounting, bank/insurance, software/IT services, media, government, education, pure retailer, pure distributor, consultancy, hospitality, healthcare provider, holding company, NGO). No free text.
2. **Reasons that argue from absence** ("pure retailer, no production", "holding, no plant") **also need a quote from the page**, checked by substring against the fetched text.
3. **Dead, parked, 404, "coming soon", bot-wall and JS-only pages never reach the model.** They are kept as FIT by a code rule. An empty page is not evidence.
4. **Ask the model whose website this is.** If the page belongs to someone else, nothing on it can disqualify this company.
5. **Let the registry win over a brochure.** If the company's own name or industry code says it makes things, an absence-based MISS is overruled.

**How to check (every run):** read at least 40 random MISS rows with name and industry and judge them yourself - a drop you cannot defend in one sentence is a wrong drop. **A MISS rate above ~8% is a defect until proven otherwise.** Audit before the cohort moves on, and grade against the company name and registry data, not against the classifier's own reason field.

---

## Phase 4.5: Confirm the Website Belongs to the Company (HARD GATE)

**Run after research and contact discovery, before normalization and any generation.**

A wrong domain attached to a company record poisons two things at once, which is why it deserves its own gate:

1. **The personalization** - you write about a business your recipient does not run
2. **The contact list** - the people you then discover work at that other company, so you are emailing strangers about a stranger's business

Searching a company name and taking the first plausible domain produces this constantly. "Acme Aceros" resolving to a large construction group's domain means every contact you find is that group's staff.

**Validate the domain before contact discovery, not after.** Check the resolved domain against the company's identity first, so discovery never starts from a wrong site. When that check is weak, discover by company name and cross-check.

**Re-run this gate whenever the domain or the contacts change.** A verdict is only valid for the domain and contact list it judged. A re-resolved domain, a salvage re-enrichment, or a new discovery wave makes it stale. A rescued false exclude is re-judged with the corrected input, never pushed quietly past its old verdict.

**For each company, judge two things independently:**

| Axis | Question |
|------|----------|
| **Site identity** | Does the scraped homepage belong to this company, a parent or subsidiary, or an unrelated business? |
| **Contact identity** | Do the discovered contacts work at this company, or at whatever the domain actually belongs to? |

**Four verdicts:**

| Verdict | Meaning | Action |
|---------|---------|--------|
| `keep` | Both check out | Proceed normally |
| `floor_personalization` | Contacts are right, site is wrong or is a group page | **Keep the lead.** Strip every homepage-derived specific and use the floor template. |
| `review` | Ambiguous | Human look before it ships |
| `do_not_write` | Contacts belong to a different company | Exclude from this push |

**Open the TAM, do not over-drop.** `do_not_write` and `review` are not terminal - apply Phase 2.8 salvage here. A contact domain that genuinely derives from the target name, or a real parent-subsidiary relationship you had not recorded, is a false exclude and should be rescued. Bias the gate so false sends are near zero and false excludes are tolerable, because false excludes are recoverable and a wrong email is not.

Store the verdict per company and have both the renderer and the pre-push gate honour it, failing closed. A verdict nothing reads is a comment.

**Freemail policy depends on your TAM.** At large companies a decision maker on a Gmail address is anomalous and should go to `review`. At small businesses it is completely normal and should be `keep`. Set this per client rather than globally.

---

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

**Record the proof, so the gate hook lets you send.** Once the read-back passes, write a proof file named for the campaign:

```bash
mkdir -p .claude/campaign-state
touch .claude/campaign-state/hardening-<campaign_id>.ok
```

The deliverability hook (`pretooluse-deliverability-hardening.sh`) refuses any activation, lead push or `push-safe.py --apply` unless a proof file newer than `HARDENING_MAX_AGE_MIN` minutes exists (default 120). It goes stale on purpose: re-run the read-back and touch the file again after any settings change and immediately before launch. Touching the file without reading the campaign back defeats the gate.

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

---

## Phase 6: Variable Generation

### 6.0 - Do you actually have an offer? (check before writing any copy)

The copy rules below assume there is something concrete to offer. If your call to action is a bare "would you be open to a quick call", stop and fix that first, because no amount of copy iteration rescues a weak offer.

Ask: what is the specific, concrete thing this person gets? An audit of something they own, a benchmark against their peers, a teardown, a calculator, a sample of the work. Something with a noun.

A good offer makes the CTA write itself, and it is the difference between "worth a reply" and "another meeting request". If the client already has a locked concrete offer, skip this and use it.

### 6.1 - Variable Format Audit (MANDATORY before writing any prompt)

**This step prevents generating thousands of variables with the wrong format. Takes 5 minutes and saves hours of rework.**

For each campaign being produced:

1. **Pull sequences from your sending platform** - extract every `{{variable}}` placeholder and its context (what comes before/after in the template).

2. **Pull real examples** - check 5-10 existing leads. If no leads yet, check sibling campaigns.

3. **Document format per variable:**
   ```
   Variable: {{e1_obs}}
   Context in sequence: "Vi que {{e1_obs}} y queria"
   Capitalization: LOWERCASE (follows "que")
   Terminal punctuation: NONE (comma follows in template)
   Word count: 8-15 words (from examples)
   Language: Spanish
   ```

4. **Compare against prompt** - check that the prompt produces output matching the required format. Flag any mismatches. Resolve before proceeding.

### 6.2 - Prompt Library Check + Validation Rules (MANDATORY before writing any prompt)

**NEVER write a prompt from scratch without checking first.**

Query your prompt library for existing prompts by task type and client. If an approved prompt exists for this task type and client, use it. If it needs minor updates, update it - don't write a new one from scratch.

If no prompt exists, write one - then save it to your prompt library BEFORE running production.

**Build your prompt library as you iterate.** Every prompt that touches production data should be saved with:
- Task type (e.g., "observation_generation", "bridge_sentence", "company_normalization")
- Client name
- Model used
- Required inputs (which database fields must be non-empty before this prompt runs)
- Output validation rules (max words, banned words, format checks)
- Notes on what it does and any quirks

This library becomes invaluable across sessions. Without it, you'll rewrite prompts from scratch each time and lose hard-won iterations.

**Validation rules are MANDATORY on every prompt record.** When saving a new prompt, document:

| Field | Purpose |
|-------|---------|
| `required_inputs` | Database fields that MUST be non-empty before this prompt runs. e.g. `["operations", "triggers", "industry"]` |
| `input_sanitization_rules` | Rules for cleaning inputs before GPT sees them. e.g. strip outdated triggers, strip banned patterns |
| `output_validation_rules` | Rules for rejecting bad outputs. e.g. max words, banned words, year checks |

### 6.2b - Input Validation Gate (HARD BLOCK - NON-NEGOTIABLE)

**NO GPT/AI call runs without validated inputs. This is the single biggest quality failure mode - missing/bad inputs passed to GPT cause hallucinated observations and high violation rates.**

**CRITICAL: Always pull leads from your sending platform, not local files (NON-NEGOTIABLE)**

When regenerating or updating custom fields for an existing campaign, ALWAYS pull the live lead list from your sending platform (with pagination). NEVER rely on a local JSON/CSV as the source of which leads exist. Leads can be added after the initial load. Verify: campaign lead count = number you process. Incident: a regeneration run missed about a quarter of the leads because the script used a stale local file.

**Before EVERY bulk AI generation step (observations, bridges, bullets, any variable):**

1. **Load required_inputs from your prompt library** for the prompt being used
2. **For each company in the batch, validate all required inputs exist**
3. **Gate decision:**

| Result | Action |
|--------|--------|
| All required fields present, no warnings | Proceed to generation |
| Required fields present, has warnings | Log warnings, proceed with caution flag |
| Missing required fields | **Do NOT send this company to that prompt.** Drop the contact to a lower opener tier (see the ladder in 6.4) and queue the company for research backfill. Log: "Tier-down {domain}: missing {fields}" |

**Never drop a contact from the cohort because research is missing.** Cohort eligibility is decided by ICP fit, persona, cooldown and DNC. Thin research changes which opener a contact gets, never whether they get an email. Backfill research in parallel; it does not block the cohort.

4. **For companies that pass the gate, sanitize inputs** - strip banned content, filter outdated triggers, flag suspicious data BEFORE the AI sees it.

5. **Report before proceeding:**
```
INPUT VALIDATION REPORT
=======================
Total companies: {N}
Passed (clean): {N} ({%})
Passed (with warnings): {N} ({%})
Tiered down (missing inputs): {N} ({%})
  - Missing 'operations': {N}
  - Missing 'triggers': {N}
  - Missing 'industry': {N}
Sanitization actions:
  - Triggers stripped (outdated year): {N}
  - Banned patterns removed from operations: {N}
  - Suspicious amounts flagged: {N}

Proceed with {N} companies at full tier, {N} tiered down? (backfill queued for {N})
```

6. **If >20% of companies are tiered down:** treat it as a signal that research underperformed, not as an exclusion. Fix and re-run research (Phase 4) for those companies so they can climb back to a higher tier. Nobody is removed from the cohort for it.

**This gate replaces the old pattern of "send everything to the model and hope for the best." A model with empty inputs produces hallucinated observations at around a 70% violation rate.**

### 6.2c - The Abstention Contract (NON-NEGOTIABLE - this is the other half of 6.2b)

**Gating the inputs is half the job. The other half is giving the model a permitted way to produce nothing.**

Telling a model not to invent does not stop it inventing. Its default behaviour is to emit something, and when the source is thin, "something" is whatever the sector implies. You have to make silence an available, explicitly preferred output.

**Four layers, all required:**

**1. The prompt carries an abstention clause.** Every prompt that turns a source into a field gets this, framed as the expected and safe answer, not as a failure:

```
NOT_FOUND is a correct, expected and PREFERRED answer. Returning it is never a
failure. Inventing a fact to avoid returning it is the worst outcome here.

Return NOT_FOUND whenever:
- The source is empty, near-empty, or an error/cookie/consent page
- The source describes a different company than the one named
- Nothing in the source is both specific and relevant
- You would have to infer from the sector, the industry code, the company name,
  or your own prior knowledge rather than read it in the source

State only what appears in the source provided. For every claim, return the exact
sentence that proves it. If you cannot produce that quote verbatim, return NOT_FOUND.
```

**2. A source check runs BEFORE the model call.** If the fetched text is empty, under a few hundred characters, an error page, a consent wall, or in the wrong language, abstain without spending the call. Cheaper and more reliable than asking the model to notice.

**3. The abstention never renders.** Store `NOT_FOUND` as NULL. The consumer checks for NULL and drops a tier, down to the floor opener (sourced what-they-make + where, then the question - see the ladder in 6.4), which carries no claim the source does not support. The token itself must never survive into an email - grep the push payload for it as a final check.

**4. A validator proves the step goes red.** Feed it a company whose source you deliberately emptied and confirm it abstains. Until you have watched it fail on known-bad input, you do not know whether it works or is silently passing everything.

**Monitor the abstention rate per batch:**

| Rate | Reading |
|------|---------|
| Near 0% on thin data | The model is inventing, not abstaining. The clause is not working. |
| Up to ~30% | Healthy. This is the system doing its job. |
| Over ~30% | Research underperformed. Fix Phase 4 rather than shipping floor templates to a third of the cohort. |

**The incident:** a research synth invented equipment for three companies whose sources were empty, thin and wrong-company respectively. The prompt had no abstention path, so it produced its best guess for all three.

### 6.2d - Clean Source Fields Before Generation (HARD BLOCK)

Any source field that gets pasted into copy word for word (products, equipment, services) must be clean before any generation runs:

- No SKUs, model or part codes, dosages or bracketed specs
- No text in the wrong language - translate it grounded in the source, or drop it
- No marketing fluff ("líderes en soluciones integrales")
- No comma lists of 3+ items pasted as a phrase

A field that cannot be cleaned to a plain category is set to empty, and the contact falls to the floor opener.

**Why:** catching a bad source field once, before generation, is far cheaper than finding it again in every rendered email.

**How to check:** run the same field-quality validator in three places - before generation, inside the renderer, and in the pre-push gate. One validator, never three copies of the logic.

### 6.3 - Iterative Improvement Loop (MANDATORY for every variable, every run)

**98% accuracy threshold. No exceptions. "Looks good on 10" is NOT sufficient for production.**

1. Pick 10-20 test companies (diverse sectors, at least 2 per major sector)
2. Generate all variables for those companies using the prompt
3. Output in Standard Format (see below)
4. Review against the quality rules in 6.4 below - apply them yourself before showing the user
5. Show output. Wait for feedback.
6. Apply changes, regenerate same 10-20, show diff
7. Count failures. If pass rate < 98% (>1 fail per 50): fix the prompt and re-test. Do not proceed.
8. Once 98% confirmed: save prompt to your library, THEN run full production

**Standard Output Format:**
```
---
[1/10] empresa.com | Sector: Logistics | Campaign: P2
Name: Nombre Apellido | Company: Empresa Ejemplo

E1 (observation): acaba de abrir un segundo almacén en Zaragoza
Bridge: y con ese ritmo seguro que queréis tener cada camión a punto...
Question: ¿cuántas revisiones de la flota seguís programando a mano?

E2 (obs_short): segundo almacén en Zaragoza
Bullet 1: [text]
Bullet 2: [text]
Bullet 3: [text]

Social Proof: proof_line_1=Similar Company A | proof_line_2=Similar Company B
Outcome: [anonymous case study outcome]
Proof sentence: [anonymous social proof sentence]
---
```

**This loop runs every time - including re-runs of existing prompts. Even if the prompt hasn't changed, verify the output still meets 98% on the current data.**

### 6.3b - Output Validation Gate (HARD BLOCK after every generation batch)

**Every AI output MUST pass validation before being accepted. Violations are auto-rejected and logged.**

**After each batch of AI-generated variables:**

1. **Validate every generated field** for every company against your output rules
2. **Validate the complete field set** per company (cross-field checks)
3. **Gate decision:**

| Result | Action |
|--------|--------|
| All fields PASS | Accept - proceed to assembly |
| 1-2 fields FAIL with fixable violations | Auto-retry: regenerate ONLY the failed fields (max 2 retries per company) |
| Structural FAIL (empty, wrong language, hallucinated) | **REJECT company.** Log and skip. |
| >10% of batch fails after retry | **STOP.** The prompt needs fixing. Go back to 6.3. |

4. **Report after validation:**
```
OUTPUT VALIDATION REPORT
========================
Total generated: {N} companies x {M} fields = {total} fields
Passed first attempt: {N} ({%})
Passed after retry: {N} ({%})
Rejected (unfixable): {N} ({%})

Top violation types:
  - Banned word in observation: {N}
  - Bridge too long: {N}
  - Bullet starts uppercase: {N}
  - Outdated year: {N}

Overall pass rate: {%} (must be >98% to proceed)
```

5. **If pass rate < 98%:** Do NOT proceed. Fix the prompt, re-run the full batch, validate again.

**Per-contact AI copy runs in batches of at most 200, with QA between batches (NON-NEGOTIABLE).** Applies to any field a model writes independently per contact (openers, bullets, bridges, proof lines). Generate up to 200 -> run an AI QA judge on a sample of that batch (at least 10%, minimum 30, or the whole batch if smaller) -> **if rejects exceed 2%, halt**, fix the prompt and re-run that batch before starting the next. Never generate the whole cohort and QA once at the end. Deterministic template assembly from a fixed set of cells does not need this; the rendered-email check already covers it.

### 6.3c - Post-Processing Layer (BETWEEN generation and validation)

**AI models stubbornly generate banned words despite prompt instructions. A deterministic regex replacement pass catches what retries cannot.**

After AI generation but BEFORE running validation:

1. **Run a regex replacement pass** on every generated field, swapping banned words for colloquial equivalents:
   - `clave` -> `importante`, `sistema` -> `equipo`, `eficiencia` -> `rendimiento`
   - `optimizar` -> `mejorar`, `implementar` -> `poner en marcha`, `integrar` -> `conectar`
   - `supervisar` -> `controlar`, `gestionar` -> `llevar`, `configurar` -> `ajustar`
   - `avanzado` -> `moderno`, `innovador` -> `nuevo`, `solución` -> `herramienta`
   - `monitoreo` -> `seguimiento`, `crucial` -> `importante`, `preciso` -> `exacto`
   - Use word boundary regex (`\b...\b`) to avoid false positives (e.g., "autoclaves" != "clave")
   - Adapt this list to your language. The principle: replace consultant-speak with bar-conversation words.

2. **Strip trailing punctuation based on template context:**
   - Check how the template uses each variable - does it append a comma, period, question mark, or nothing?
   - Strip trailing periods from obs if the template appends punctuation directly after the variable
   - This is per-campaign, not universal - read the E1/E2 templates before deciding

3. **Then run validation** on the post-processed text

**Why:** Post-processing caught 3 additional fixes that 5 retry attempts couldn't solve - GPT kept regenerating banned words for certain industry companies despite explicit bans in the prompt. The regex replacement layer is cheap insurance.

### 6.3z - END-STATE EMAIL SPOT-CHECK (NON-NEGOTIABLE, AUTO-TRIGGER)

**This rule is a HARD GATE. The words "shipped", "pushed", "complete", "done", "ready" - for any campaign - are FORBIDDEN until you have personally rendered and read 10+ live emails in the same response cycle. No exceptions. Not even for "small fixes". Not even for "a quick straggler patch". Not even when "the JSON looked perfect".**

**Auto-trigger conditions (any of these = run the spot-check IMMEDIATELY):**
- You just pushed any custom_field update to your sending platform
- You just changed a sequence template
- You just regenerated any obs/clause/bridge/bullet for >10 leads
- You're about to write "shipped" / "pushed" / "complete" / "done" / "ready" in your reply

**You MUST QA the FULL RENDERED EMAIL pulled from your sending platform, never your variables in isolation or your memory of the template.**

**Why this exists:** Variables look fine in isolation, templates look fine on their own. But the **end state** is what the lead receives - the template + custom field values + spintax substitution + junction punctuation, all rendered together. Bugs hide in the seams: a comma in the template + a comma at the end of a custom field = `,,`. A period in a clause + the next sentence start = `.. ?`. None of these are visible until you render the whole thing.

**The rule:**

Before reporting "spot-check passed" / "shipped" / "ready for review" on any campaign, you MUST:

1. **Pull the live sequence template** from your sending platform (NOT what you remember writing)
2. **Pull live leads** with their current custom_fields
3. **Render the full email** by substituting custom fields into the template AND collapsing spintax AND stripping HTML. That includes the static parts that live in the template, not the variables: **the greeting resolved to the real first name, and `%signature%` resolved to the assigned inbox's real signature.** A body-only dump hides exactly the seams you are checking. If a signature is not assigned yet, show a clearly labelled placeholder rather than leaving it out.
4. **Read the rendered output as a recipient would read it** - the entire email body, top to bottom
5. **Scan the rendered text for punctuation collisions**: `,,` `..` `.,` `,?` `.?` ` ,` ` .` `((` `))` and any double space. **Also check for a duplicated P.S.:** a P.S. inside a body variable plus a P.S. variable the template appends after the signature renders two of them in every email.
6. **Sample properly: 10% of the campaign, floor 30, ceiling 100** - plus **any specific lead the user flagged**
7. **Render BOTH the opener and the follow-up**, not just E1
8. **Report the actual rendered text** in your reply, not just "looks good"

**On sample size.** Ten is not a sample, it is a glance. At n=10 a defect affecting one email in six has only about an 82% chance of showing up, so roughly one bad cohort in five ships clean-looking. At n=30 that detection rate goes to 99.5%. On a big push, n=100 also gives you a usable estimate of the defect *rate*, not just its existence.

We shipped a cohort where 16% of openers carried wrong equipment claims, because the 10-lead sample happened to miss them. Recipients were told about machinery their business does not use.

**Render the follow-up too.** Step-2 emails fail in ways step 1 cannot show you: empty bullet fields rendering as bare `- ` lines, a missing social-proof anchor, bullets templated from the wrong sector. A separate check found a handful of genuinely bad follow-ups in a cohort whose openers were all clean.

**If any rendered email has a punctuation collision, the spot check FAILS regardless of how clean the variables look in JSON.**

**Anti-patterns (these are NOT spot-checks):**
- "I checked the JSON and the clauses look clean" - NOT A SPOT-CHECK
- "I sampled the variables and they pass the validator" - NOT A SPOT-CHECK
- "The prompt forbids hedge words so they're definitely not there" - NOT A SPOT-CHECK
- Reading variables out of context, trusting your memory of the template, or believing the validator caught everything - all FAIL

**The only valid spot-check is: pull -> render -> read the whole thing.**

### 6.4 - Quality Rules (NON-NEGOTIABLE - apply at every generation step)

**Grade 5 / Bar Test / Single Data Point - these rules override every other instruction.**

**The opener tier ladder (use the highest tier the evidence supports, and no higher):**

Copy rules tell you what a good opener looks like. They do not tell you what to do when the research is thin, which is exactly where invention happens. So rank the openers and define the floor.

**Signal priority depends on the persona.** Different roles answer different signals, so rank per persona and pass that order to the generator at call time. Never hardcode one universal order. A starting point:

| Persona | Priority order (left = best) |
|---------|------------------------------|
| CEO / MD / CFO (strategic) | Company signal (group level) -> company signal at their site -> personal signal -> concrete detail -> floor |
| Site or plant owner | Company signal at their site -> personal signal -> group-level company signal -> concrete detail -> floor |
| IT / digital | Personal signal (tools, credentials, career move) -> company signal at their site -> concrete detail -> floor |
| Operations / maintenance / quality | Personal signal (role change, credentials) -> company signal at their site -> concrete detail -> floor |

| Tier | Anchored on | Example shape |
|------|-------------|---------------|
| **Personal signal** | Something true of the *person* | "vi que llevas unos meses al frente de operaciones" |
| **Company signal** | A dated event at the company | "vi que habéis abierto una nave nueva en Zaragoza" |
| **Concrete detail they own** | Equipment, sites, headcount, something physical | "con tres plantas a dos turnos" |
| **Floor** | Sourced what-they-make + where, then the question | "He visto que fabricáis envases en Valencia y quería preguntarte: ¿...?" |

Rules for the ladder:

- **Every tier needs a source quote.** No quote means you drop a tier, not that you write it anyway.
- **The floor is still sourced.** It states what they make and where, taken from the source, then asks your question. If they reply "we don't make that any more", that is engagement. A fully generic floor ("sois una empresa del sector") gets zero replies.
- **Only when even product and location are missing** does the opener fall to a short question that references the industry category alone.
- **Never fall UP a tier.** If the equipment data is missing, drop a tier. Do not infer typical equipment for the sector - that is exactly how a company gets told about machines it does not own.
- **Track the tier distribution per cohort.** Mostly floor means your research step underperformed and you should fix Phase 4, not ship it.
- **No template for a signal + persona pair falls through to the floor.** If the chosen signal has no template for this persona, route the contact to the floor opener. Never return nothing and silently drop the contact from the push.

**Opener fact must set up the question.** Run an AI judge on every (opener, question) pair: does the fact plausibly lead into the question that follows? A store count or a pure financial figure before an operations question reads oddly. Flagged rows go to salvage (Phase 2.8): swap to a better signal, fall to the floor, or keep with a written reason. Test the judge against a known-bad pair first.

**Plain language in openers.** No certification codes or version numbers (say "la certificación de seguridad alimentaria", not the standard's code), no model or series codes, no acronyms a non-specialist would not know, and no old facts written as fresh news ("me enteré de que en 2014..."). Check it per contact with the same judge, not by trusting the prompt.

**Personal facts take singular grammar.** Tenure and career moves describe one person: "ahora que **llevas** unos meses al frente", never "ahora que **llevan**". Company facts stay in the company register. Use a checker scoped to biography phrases, and prove it goes red on a known-bad line before you trust it.

**Whose news is it.** A fact written in the second person must be the reader's own company's. Group or parent news is used only when it lands on the reader's own site, country or business, and only in the third person, as the group's act: "Grupo Ejemplo está invirtiendo en la planta de Sevilla", never "estáis invirtiendo". Group news about somewhere else, or anything you cannot attribute, falls to the floor. A subsidiary sitting on its group's website may still say what it makes, but nothing that happened to it.

**Multi-site safety.** If a company has 2+ sites and you do not know which one the contact works at, do not name a city. Use "vuestras plantas" or similar instead of pinning one location.

**Bridge framing: achievement, never diagnosis.** The bridge is a compliment that leads into the question: it praises their level or ambition and leans toward something they would want. It never names the pain and never proposes a problem the lead did not mention - the pain question belongs in the line after the bridge. "Con ese ritmo de crecimiento, seguro que queréis tenerlo todo a la vista" is right. "Growing that fast means your maintenance schedule is broken" is an insult with a question mark on the end.

**Bridges repeat when a model writes them one at a time.** Each call cannot see the rest of the cohort, so it collapses onto a few favourite sentences, which becomes a fingerprint. Either pick bridges from a large, varied, pre-approved pool (keyed deterministically per contact), or run the 15% check in 7.1 across the whole cohort's bridges before push.

**Single data point rule:**
- One fact. One. Pick the single most relevant finding. Ignore the rest.
- "60 years running AND three awards" = two facts = FAIL. Pick one.
- The "y" / "and" test: can the second part be directly derived from the first? If not, cut it.
- After a trigger event, stop. NEVER add "para la fabricacion de X" explaining what they make.

**Bar conversation test:**
- Read every output out loud. Would you say this to someone over a beer? If it sounds like a brochure or consultant deck, rewrite it.
- Banned words (Spanish; adapt to your language): implementar, optimizar, integrar sistemas, visibilidad operativa, líder, excelencia
- Use instead: poner, conectar, ver, saber, montar
- Adapt banned/replacement word lists to your language. The principle: no one talks like a McKinsey deck at a bar.

**Grade 5 reading level:**
- Max 15 words per sentence. Aim for 10.
- One idea per bullet/sentence.
- Concrete over abstract: "tus 12 hoteles" not "vuestros centros"

**NEVER condescending:**
- BANNED (Spanish; adapt to your language): "se te escapan detalles", "sin darte cuenta", "no tienes control", "te falta", "pierdes de vista"
- Frame challenges as natural operational realities that come with growth - not personal failures

**All copy must be in the campaign's target language.** Wrong language output = hard fail.

**Opening rules for observations:**
- Triggers: state only the trigger. "Vi que estáis abriendo el despacho de Valencia." - stop there.
- Equipment observations: use specific equipment names when available, never fall back to product name
- **Format depends on campaign type** (check client's campaign-config):
  - Factual-observation campaigns: open with "I saw that..." / "Vi que..." - MANDATORY
  - Trigger/project-framed campaigns ("For a project like..." / "Given your..."): noun-phrase fragment, NOT "I saw that..."
  - When in doubt, check the sequence template for how `{{observation}}` is used
- **COMPANY NAME IN OBSERVATIONS (ZERO TOLERANCE):** The observation field must NEVER contain the company name, parent name, subsidiary name, or any recognizable variant. The template already includes `{{company_name}}` - including it in the observation causes double mention. When the project IS the company name, reference LOCATION or ACTIVITY instead.
- Tagline test: if the company could have written the sentence themselves on their homepage, it's a tagline not an observation. Observations must contain a specific verifiable fact.
- **No marketing language or editorial opinions in observations (ZERO TOLERANCE):** Never use slogans, superlatives, or subjective descriptions from source articles/websites as project names or facts. "America's most urgent transit project" is an editorial opinion, not a project name - use the actual name or location. Same applies to: "world-leading", "award-winning", "revolutionary", "game-changing".

**NEVER use:**
- "Does that resonate?" (banned - too generic)
- "Many [persona]..." (banned - sounds formulaic)
- Taglines as observations

**Subject lines: the directory test (run before locking any subject).**

Ask: could this be mistaken for an automated notification from a review site, a listings service, or an aggregator? If yes, rewrite it. The subject has to read like a person, not a service.

A city name alone always fails. "a quick question from Madrid" reads like an automated digest and gets skipped without being opened. Use something true of that one business instead: a recent event, a specific count, the business's own name, the topic you are actually writing about.

Decision order:
1. If you have a specific fact about **this** company, use it
2. Otherwise use a theme that hints at the relevant topic without naming a city
3. Never ship a city-only subject

We once ran a full cohort with a city-only subject before catching this. The fix was a subject naming the topic the email was actually about.

**Unsourced AI lines that describe the company back to itself are POISON (from published analyses of 1,500+ campaigns - see Credits in the README; the percentages below are that source's):**

This is about generic, unsourced first lines, not about observation openers. A sourced observation (one specific, quoted, relevant fact, per the ladder above) is the method this skill uses.

- Generic AI first-lines ("I saw your company helps people with X...") consistently underperform - significantly WORSE than no personalization
- What WORKS (64% top performer): targeted product-focused AI that calculates YOUR value for THEM
  - GOOD: "{{company_name}} could save {{savings}} annually by switching to [approach]"
  - GOOD: "For {{customer_type}} businesses like {{company_name}}, we typically see [outcome]"
- What ALSO WORKS (44% top performer): specific enriched data proving real research
  - GOOD: "Saw {{company_name}} has a {{rating}}-star rating on Google..."
  - GOOD: "Your {{cuisine}} restaurant in {{town}}..."
- What FAILS (majority poor): describing THEIR company back to them
  - BAD: "I saw that {{company_name}} helps customers with [AI-generated description]..."
  - BAD: "As a leader in [AI-scraped industry], I thought you'd be interested..."
- Core rule: every AI line must carry something specific - a sourced fact or a value prop for them - never a generic description of what they do

**CTA Rules (same published analyses - value-first, ALWAYS questions):**
- BEST: "If we could help with X, would that be useful?" (13% top-performer rate)
- GOOD: "Thoughts?" / "Does this sound familiar?" (11%)
- OK: "Would a 15-minute call next week work?" (9%) - but value CTAs beat this
- BANNED: Passive CTAs ("if you're interested...", "feel free to...", "when you have time...") - 50% fewer responses
- BANNED: Statement CTAs ("Let me know" without a question)
- ALL CTAs must be questions, never statements. The CTA should offer value, not request time.
- Hierarchy: value question > lead magnet offer > meeting request
- The meeting often comes naturally from the reply conversation - don't force it in the email CTA

**PS Line Rule (same published analyses - significantly more responses):**
- EVERY E1 email MUST include a PS line with a DIFFERENT value prop angle
- The 5 universal business value props: save time, save money, make more money, reduce risk, raise status
- If main body angle = "save time", PS = "make more money" (or vice versa)
- The PS must be a genuinely different benefit lens on the same product - not the same pitch restated
- Format: "PS - [Different angle one-liner]. {Would that be interesting too?|Curious if that matters more?|Is that closer to what you need?}"
- Generate the PS as a separate variable ({{ps_line}}) using the same AI model, with the main body angle as input context
- This applies to ALL campaigns going forward - no exceptions

**Case Studies / Social Proof (same published analyses - "taking this to the bank"):**
- DO NOT name the case study company in email copy
- Naming case studies correlated with average and below average campaigns
- Just describing outcomes without naming correlated with above average and excellent campaigns
- Reasoning: unknown company name = no resonance; known company = "I'm not them, doesn't fit me"
- DO: "A logistics company with 40 depots cut missed pickups by 30%"
- DO: "One of our clients in [their industry] cut processing time from 2 weeks to 3 days"
- DON'T: "We helped Reddit cut missed pickups by 30%"
- DON'T: "Companies like Acme Corp and Mega Inc trust us"
- Social proof in the email must be anonymous. Your lookup tables may store company names internally for reference, but the email-facing text must describe outcomes without naming companies.

### 6.4c - Edge Case Manual Cleanup Pass (MANDATORY before push)

**EVERY bulk variable generation run WILL have edge cases. Plan for it. Do not skip this.**

No matter how strict the prompt, validator, or QA scoring, batch generation at scale (500+ records) will always produce 1-5% of outputs that slip through with subtle issues - hedge words mid-sentence, awkward phrasing, near-duplicate openers, occasional grammar misses. **This is not a sign that the prompt failed. It is a sign that you are running at scale.**

**Required workflow after every bulk run:**

1. **Scan ALL generated records** (not just a sample) for known edge-case patterns:
   - Hedge words anywhere in the sentence (not just openers; Spanish, adapt to your language): `imagino`, `supongo`, `seguro que`, `probablemente`, `creo que`, `me imagino`
   - Colloquial spam openers that leaked (Spanish; adapt to your language): `Mira,`, `Oye,`, `Pues,`, `Vaya,`
   - Banned words from your client-specific rules
   - Suspicious near-duplicate openers (top 5 starters >10% of batch each)
2. **Fix deterministically with regex** where possible (hedge removal is easy: `, imagino que X` -> `, X`).
3. **Push fixes back to your sending platform** via the same lead update endpoint.
4. **Add the new edge-case patterns to the prompt's banned list** so the next run catches them at generation time. Do this BEFORE moving on - do not let the next session rediscover these.
5. **Confirm to the user** with: "Edge cases manually cleaned. Pattern X added to v{N+1} prompt for next time."

**Why this rule exists:**
- You must publish campaigns. You cannot iterate forever on a prompt.
- Manual cleanup of 50-100 edge cases takes 5 minutes via regex; another iteration cycle takes 30+ minutes and rarely catches everything.
- Each run also teaches you new patterns to ban - the prompt should improve every session, not stay frozen.
- Leaving hedge words in production emails is unacceptable. Spending 4 more iterations to kill the last 2% is also unacceptable. Manual fix + prompt update is the right tradeoff.

**Anti-pattern:** "I'll iterate one more time to catch these." STOP. Fix manually, update the prompt, ship.

### 6.4b - Copy Grader Gate (MANDATORY - self-iterating until Excellent)

**After generating all email copy (sequences, variables, PS lines), run a Copy Grader before proceeding.**

Score the campaign using these weights:
- **Composite: (0.40 x Copywriting) + (0.35 x Targeting) + (0.25 x Variables)**

**Scoring levels:**
| Score | Rating | Action |
|-------|--------|--------|
| 80-100 | Excellent | Proceed to Phase 7 |
| 65-79 | Above Average | Flag issues, proceed if user approves |
| 50-64 | Average | Auto-rewrite and re-score |
| 35-49 | Below Average | Auto-rewrite and re-score |
| 0-34 | Poor | Full rewrite required |

**Self-iteration loop (NON-NEGOTIABLE):**
1. Score the campaign copy
2. If score < 80 (not Excellent): identify the weakest scoring component
3. Auto-rewrite the weakest area (subject lines, body, CTAs, variables, PS lines)
4. Re-score
5. Repeat until score >= 80 (Excellent) or 3 iterations completed
6. If 3 iterations and still < 65: STOP and flag for user review with specific issues
7. Report: "Copy Grader: [score]/100 ([rating]). [strongest area] / [weakest area]. [iterations needed]."

**Anti-pattern scan (run as part of grading):**
- GENERIC_AI_COMPANY_OBSERVATION: -30 points (critical)
- SPAM_CRITICAL: -30 points
- FAKE_REPLY (Re:/Fwd:): -15 points
- NO_PERSONALIZATION: -15 points
- MISSING_CTA: -15 points
- WEAK_CTA (passive): -7 points
- EMAIL_TOO_LONG (>150 words E1): -7 points
- BUMP_ONLY_FOLLOWUPS: -7 points
- NO_PS_LINE: -7 points (every E1 needs a PS)
- NAMED_CASE_STUDY: -7 points (case studies should be anonymous)

### 6.5 - Model Selection

**Default to the small model. Upgrading is a decision someone makes, not a reflex when output looks bad.**

**Pin the model per prompt.** Store the model next to each prompt in your prompt library and use that one. For a new prompt, default to the cheapest capable small model (GPT-4o-mini class), and a Haiku-class model for tone-sensitive copy.

| Task | Default | When to reconsider |
|------|---------|-----------|
| Company name normalization | Cheapest small model (GPT-4o-mini class) | Never. This task does not need more. |
| Classification, extraction, ICP checks | Cheapest small model (GPT-4o-mini class) | Only after a well-iterated prompt still misses 98% |
| Observation generation | Pinned model, else cheapest small model | Only after a well-iterated prompt still misses 98% |
| Bridge sentences, other tone-sensitive copy | Pinned model, else Haiku-class | Only after a well-iterated prompt still misses 98% |
| Bullet generation | Pinned model, else cheapest small model | Only after a well-iterated prompt still misses 98% |
| Quality review | Haiku-class or cheapest small model | Never |
| Pipeline design, config, debugging | Your best model | One-off reasoning, not a loop |

**Show a cost estimate before every paid run:** number of records, model, estimated dollars. Get agreement, then run. If the real cost heads past twice the estimate, stop and re-estimate.

Bad bulk output is a prompt problem until proven otherwise. Before upgrading a model in a loop, state the cost difference at the actual batch size and get a human to agree to it. A thousand-record run at a large model is 10-30x the cost of the same run at a small one, and it rarely fixes what a better prompt would have fixed.

**Prompt caching is mandatory in any loop over about five calls.** This is what the variables-at-the-end rule exists for:
- First 1,100+ characters byte-identical across every call
- Per-record data last, under `## VARIABLES:`
- Send the provider's cache directive
- One stray timestamp or ID near the top voids the cache for the entire run

Put this in one shared calling function rather than trusting each script to remember it. An uncached loop burned a day's budget in an afternoon, and it also overwrote its own results with error strings, so the money bought nothing.

### 6.6 - AI Cost Reporting (NON-NEGOTIABLE)

After EVERY production run that calls external AI APIs, immediately report:
- Number of API calls per model
- Estimated token usage
- Estimated cost in USD

Do this before moving to the next step.

### 6.6b - Greeting Name (HARD BLOCK)

Never ship a generic greeting where the recipient's real first name is findable, and never ship a first name that belongs to someone else.

1. **Extract the first name with a model, not a regex.** Full-name fields hold titles, compound first names ("José Luis") and sometimes the business name itself.
2. **Fallback order:** the full-name field -> the email local part when it is clearly a person (`nombre.apellido@`), not a role inbox (`info@`) -> the company's own website.
3. **Ship the name only if it is confirmed to belong to the recipient:** the first name appears in the business name, in an own-domain personal email, or the website names them as the owner or lead. A matching surname alone is not confirmation - family businesses share surnames across relatives.
4. **Found but unconfirmed = do not use it.** Fall back to a neutral greeting ("Hola,"). A wrong first name is worse than no name: it draws "that's not my name" replies and burns the lead.

**How to check:** record per contact which greeting path it took (resolved, confirmed or fallen back, e.g. a `greeting_status` column), count them per cohort, and hand-check a sample of confirmed names against the email and business name.

### 6.7 - Variable Assembly

After observation generation, assemble all deterministic fields per contact using the lookup tables in your client config (sections 3-7 of [`setup/campaign-config.template.md`](../../setup/campaign-config.template.md): industry map, persona x sector, social proof, proof sentences, bullets):

- `proof_line_1`, `proof_line_2` from the social proof table (by sector/persona)
- `proof_detail`, `outcome_tail` from the proof table
- `proof_sentence` from the proof sentence table
- `bullet1`, `bullet2`, `bullet3` from bullets table (by sector/persona)
- E2/E3 body pre-computation with spintax resolution per contact
- `colleague_name` for name-drop technique (see below)

#### Name Drop Expansion (E2 Personalization)

For E2 follow-ups, find colleagues at the same company to mention. This is simple personalization that dramatically increases response rates for minimal cost.

**Source priority for colleague names:**
1. **Same campaign, other personas:** Query contacts for other KDMs at the same company_domain already loaded in other campaigns for this client
2. **Your contacts database:** Query all contacts at the same company_domain across all clients
3. **Prospeo API:** If no colleagues found, query Prospeo's company enrichment to find other people at the company

```sql
-- Find colleagues in your database
SELECT first_name, last_name, job_title
FROM contacts
WHERE company_domain = $target_domain
  AND email != $current_contact_email
ORDER BY
  CASE WHEN job_title ILIKE '%director%' OR job_title ILIKE '%VP%' THEN 1
       WHEN job_title ILIKE '%manager%' THEN 2
       ELSE 3 END
LIMIT 1;
```

Save as `colleague_name` field. If no colleague found, leave NULL - the E2 template should have a variant without name-drop.

Save all assembled data to a local results file as a convenience copy (6.8 is the real persistence). Checkpoint every 50 companies.

### 6.8 - Persist Generated Variables to Database (NON-NEGOTIABLE)

**Generated variables (observations, bullets, bridges, E2/E3 bodies) cost real money and time to produce. They MUST be saved to your database so they survive context resets and can be audited.**

**This applies equally to new campaigns AND top-ups/updates of existing campaigns. There is no "update path" that skips this step.**

#### A. Save to `campaign_variables` (PRIMARY store for per-contact variables)

Every contact that gets variables generated MUST have a row in your campaign variables table:

```sql
INSERT INTO campaign_variables
  (contact_id, company_id, campaign_id, client_name, persona,
   observation, obs_short, signal_type,
   bullet1, bullet2, bullet3, proof_sentence,
   model_used, generation_status, created_at, updated_at)
VALUES ($contact_id, $company_id, $campaign_id, $client, $persona,
        $obs, $obs_short, $signal_type,
        $b1, $b2, $b3, $proof_sentence,
        $model, 'generated', NOW(), NOW())
ON CONFLICT (contact_id, campaign_id) DO UPDATE SET
  observation = EXCLUDED.observation,
  signal_type = EXCLUDED.signal_type,
  updated_at = NOW();
```

**`signal_type` is MANDATORY** - every observation must be classified. Standard values:
- `expansion`, `hiring`, `leadership_change`, `merger_acquisition`, `partnership`
- `product_launch`, `award`, `regulatory`, `financial`, `strategic_initiative`
- `high_competition`, `competitor_activity`, `market_change`
- `longevity`, `generic` (last resort only)

This enables A/B analysis of which observation angles perform best per client/sector.

#### B. Save to `companies.personalization_data` (research data)

```sql
UPDATE companies
SET personalization_data = personalization_data || $generated_fields::jsonb,
    updated_at = NOW()
WHERE domain = $domain AND client_name = '{CLIENT}';
```

#### C. Update `contacts` campaign assignment

```sql
UPDATE contacts
SET assigned_campaign = '{campaign_label}',
    updated_at = NOW()
WHERE id = $contact_id AND client_name = '{CLIENT}';
```

**Why this matters:** In production, we lost research data and observations because they were only in CSV exports - never saved to the database. That was expensive to recover.

**Write per contact, inside a try/except, as each one is generated.** Same rule as Phase 4.3 and for the same reason. Generation is the most expensive step in this pipeline, so it is the worst place to batch up work in memory and hope the final write succeeds.

Report the run as `attempted / succeeded / failed` with the failing contact IDs. A run that reports "done" while silently dropping 4% of its output is worse than one that errors, because you find out from a recipient instead of from a log.

### 6.9 - Save Campaign Copy to Version History (NON-NEGOTIABLE)

**Every piece of campaign copy MUST be versioned before pushing to your sending platform.**

After finalizing sequences (subject lines, E1/E2/E3/E4 bodies):

```sql
INSERT INTO campaign_copy_versions
  (client_name, campaign_label, campaign_id, sequence_step, variant,
   subject, body_html, version, change_note, source, pushed)
VALUES ($client, $label, $campaign_id, $step, $variant,
        $subject, $body, $version, $note, 'claude_code', false);
```

- Insert one row per sequence step per variant (E1-A, E1-B, E2-A, etc.)
- Increment `version` from the max existing version for that campaign+step+variant
- Set `change_note` to describe what changed (e.g., "Initial production", "User: shortened bridge")
- Mark `pushed = false` until Phase 8 confirms the push

---

## Phase 7: Pre-Push Validation

### 7.0 - campaign_variables Save Audit (HARD BLOCK)

Before ANY push, verify all contacts being pushed have rows in your campaign variables table:

```sql
SELECT c.email, c.id
FROM contacts c
WHERE c.client_name = '{CLIENT}'
  AND c.assigned_campaign = '{campaign_label}'
  AND NOT EXISTS (
    SELECT 1 FROM campaign_variables cv
    WHERE cv.contact_id = c.id
      AND cv.campaign_id = '{campaign_id}'
  );
```

If this returns ANY rows: **STOP. Do not push.** Go back to Phase 6.8 and save the missing variables first.

**Why:** Without this audit trail, when a lead replies "your information is completely wrong", there is no way to diagnose what was sent to the rest of the campaign. You'd have to pull your sending platform one lead at a time.

### 7.1 - Copy Variation Check: no line in more than 15% of emails (HARD BLOCK)

Spam filters do not read one email. They compare everything leaving your inboxes and look for the same text going out at volume across many domains and mailboxes. Each email on its own can look personalised while the campaign as a whole is one template. This check measures what the filter measures: the FINAL emails, with every custom field filled in and every spintax block expanded.

**The rule, per sequence step (E1, E2, E3...):**
- **No body line reaches more than 15% of recipients.** A line's share is the recipients who get it, divided by its spintax branches. A line every lead gets with 4 options reaches ~25%, so it fails.
- **Zero fixed body lines.** A line identical for the whole cohort, with no branching, fails on its own. A varied opener followed by a fixed tail does not count as varied.
- **At least 90% of emails are distinct** from each other once short merge tokens (name, company, city) are masked. A plain mail-merge where only `{{first_name}}` changes is ONE template to a filter, however unique the strings look.
- **Excluded from the count:** greeting lines, sign-off lines, the inbox signature, unsubscribe lines and URL-only lines. Vary those anyway (see below), but they are not scored here.
- **A/B variants are weighted by their send share.** A line that lives in one of three variants reaches a third of recipients, not all of them.

**How to run it - the code (`scripts/check-copy-variation.py`, no dependencies beyond Python 3):**

```bash
# Before sending: build a JSON file of your templates and per-lead fields, then
python3 scripts/check-copy-variation.py --rendered rendered.json --client ACME

# After loading leads into Smartlead (reads templates, A/B variants, leads and every inbox signature)
SMARTLEAD_API_KEY=... python3 scripts/check-copy-variation.py --campaign 1234567 --client ACME
```

`rendered.json` shape:

```json
{
  "campaign": "acme-e1",
  "signature": "Nombre Apellido<br>Acme",
  "sequences": [
    {"id": "E1",
     "template": "<div>{Hola|Buenas} {{first_name}},</div><br><div>...</div><br><div>%signature%</div>",
     "leads": [{"custom_fields": {"first_name": "Nombre", "company": "Talleres Ejemplo"}}]}
  ]
}
```

Exit `0` = PASS (report written), `1` = FAIL (the report and the worst offending lines are printed, with their share), `3` = nothing to measure yet (a live campaign with 0 leads). Under 20 leads it asks for `--small-cohort-ack` because the shares are too noisy to trust. Use `--allow-fixed-line "<exact line>"` only for a line the client legally requires.

**How to run it - with Claude or Codex instead:**

> Here are all the final emails for this campaign step, one per recipient, with custom fields filled in and spintax already resolved. Ignore greetings, sign-offs, signatures, unsubscribe lines and lines that are only a URL. Treat names, company names and cities as placeholders. Split every email into lines. For each line, count how many emails contain it and give the share of the total. List every line above 15%, every line that appears in 100% of emails, and the share of emails that are distinct from each other. Do not rewrite anything yet.

For large cohorts the script is more reliable than a model counting by eye; use the prompt for a first pass or a small list.

**When it fails:** add branches to the named line, or rewrite it, then re-run until it passes. On the most-repeated lines (opener, call to action) you need roughly 8 or more renderings for any one version to stay under 15%: three 2-option swaps, or two 3-option swaps.

**Spintax rules that get you there:**
- **Word and short-phrase spintax only.** Sentence-level swaps (`{Whole sentence A|Whole sentence B}`) are banned. Spin words and short phrases: `{real|clara}`, `{captar|atraer}`, `{nos dimos cuenta|vimos|notamos}`.
- **Every line moves.** The share cap is the binding rule; spin density is how you reach it.
- **10-15 spintax groups per email.** Above 15 body groups the copy starts to read machine-spun.
- **At least 2 word or phrase swaps in every body sentence.** One swap in an otherwise identical sentence is sentence-level rotation in disguise. Count per sentence, not per email.
- **2-3 options per swap at most.** More options mostly adds weak ones.
- **No thesaurus synonyms.** Every option must read naturally out loud: `{Te lo pregunto|Te pregunto}` works, `{pregunto|inquiero|interrogo}` does not.
- **If you resolve spintax in code per contact with a seeded random generator, use the high bits, not the low bits.** A linear congruential generator's low bit alternates every step, so taking `state % n` directly collapsed 8 possible variants to 2 across a whole cohort. Shift first, for example `(state >> 11) % n`. Then run a spread check: count how many contacts got each combination and confirm all of them appear roughly evenly.
- **Subject lines: at least 10 quality-passing variants per persona**, and no single rendered subject above ~10-15% of sends. Count branches and shares, not raw unique strings (personalisation inflates string counts).
- **Vary the signature and the unsubscribe wording across inboxes.** They are the most repeated, most filter-visible strings in a send and most teams never touch them.
- **Never use time-dependent phrases** ("esta semana" / "this week") - they break on some days.
- **Never put `{{variables}}` inside spintax braces** - `{Hello {{first_name}}|Hi {{first_name}}}` breaks most sending platforms. Keep variables outside: `{Hello|Hi} {{first_name}}`.
- **Spintax is a deliverability tool, not a quality tool.** It stops pattern detection; it does not raise reply rates.
- **A bounce spike on a validated list with stable inboxes is a copy problem first.** Expand subject and body variation before you replace domains.

### 7.2 - Email Status Gate (HARD BLOCK - runs before everything else)

**APPROVED statuses: `valid` and `deliverable_catchall` ONLY.**

Run against the exact set of contacts selected in Phase 2:

```sql
SELECT email, email_status
FROM contacts
WHERE id IN ({contact_ids_selected_in_phase_2})
  AND (email_status IS NULL OR email_status NOT IN ('valid', 'deliverable_catchall'))
```

**If ANY rows returned: STOP. Do not proceed to push.**

This should never fire if Phase 2.2 ran correctly - but it acts as a double-check against:
- Client scripts that bypassed the Phase 2.2 SQL filter
- Contacts whose status changed between Phase 2 and Phase 7
- Manual additions to the push set

**Auto-requeue unverified catchall contacts:**

For any blocked contacts with `email_status = 'catch_all'` (unverified), automatically queue them for verification. Unverified catchall domains have a ~38% hard bounce rate. Only `deliverable_catchall` (verified individual mailbox via BounceBan or similar) is allowed.

### 7.2b - DNC Gate - Contact AND Company Level (HARD BLOCK)

**Check BOTH contact-level and company-level DNC.**

```sql
-- Contact-level DNC
SELECT c.email, 'contact' as dnc_level
FROM contacts c
WHERE c.client_name = '{CLIENT}'
  AND c.do_not_contact = true
  AND c.email IN ({list of push emails});

-- Company-level DNC (catches domain-wide blocks)
SELECT c.email, comp.domain, 'company' as dnc_level
FROM contacts c
JOIN companies comp ON comp.domain = SPLIT_PART(c.email, '@', 2)
  AND comp.client_name = '{CLIENT}'
WHERE comp.do_not_contact = true
  AND c.email IN ({list of push emails});
```

**If ANY rows returned: BLOCK those leads.** Also check subdomain matches (e.g., `mail.bigcorp.com` should match `bigcorp.com` DNC).

**Incident:** Contacts from DNC companies were pushed to campaigns despite the company being DNC'd by client request. Root cause: only contact-level DNC was checked. This gate prevents that.

### 7.3 - Cross-Campaign Dedup Gate (HARD BLOCK - NON-NEGOTIABLE)

**Dedupe on SEND HISTORY, not on campaign membership.**

> **This rule was reversed in August 2026.** The original version of this gate blocked any lead present on any other active or paused campaign. That is blind to whether anything was ever sent, and it over-blocks badly: it silently rejected over half of one push, and a sample of those showed only about 2% were genuine cooldowns. The rest were people sitting untouched on a paused campaign from months earlier. If your platform offers its own cross-campaign dedup switch, turn it off - it makes the same mistake for the same reason.

The gate:

1. Take the exact set of emails you are about to push
2. Check each against your outreach log using `COALESCE(first_sent_date, loaded_date) > NOW() - INTERVAL '90 days'`
3. Block only those inside the window
4. Separately, block anyone currently mid-sequence on another campaign (Phase 2.4 in-flight check) - that is a real conflict, because two live sequences to one person at once is the failure everyone notices

**Person-level dedup is absolute and separate from all of this:** the same individual never appears twice in one push, ever. That check is on the push set itself and needs no external lookup.

**This is why push-time logging matters (Phase 8).** The old rule existed because the outreach log was only written after the platform sent, leaving a blind window where a freshly pushed lead looked untouched. Logging at push time closes that window and makes the log a real-time source of truth - which is what lets this gate be accurate instead of merely conservative.

**Wrap it in one function.** Every path that pushes leads - the main pipeline, a top-up script, a one-off recovery, a colleague's notebook - calls the same gate. Three duplicate-lead incidents in one week, hundreds of duplicates, all came from scripts that went straight to the platform API and skipped this.

### 7.3b - Cooldown Gate (HARD BLOCK)

**Check if any contacts were contacted in the last 90 days on a different campaign.** Same one cooldown as Phase 1.2, same `COALESCE(first_sent_date, loaded_date)`.

```sql
SELECT c.email, ol.campaign_name, ol.loaded_date,
  EXTRACT(day FROM NOW() - ol.loaded_date) as days_ago
FROM outreach_log ol
JOIN contacts c ON c.id = ol.contact_id
WHERE c.email IN ({emails_being_pushed})
  AND ol.client_name = '{CLIENT}'
  AND COALESCE(ol.first_sent_date, ol.loaded_date) > NOW() - INTERVAL '90 days'
  AND ol.campaign_name != '{target_campaign_name}'
```

**If ANY rows returned: BLOCK those leads.**

Note: This catches contacts from COMPLETED/STOPPED campaigns that the dedup gate won't see (since it only checks active/paused). A contact could have completed their sequence on a now-stopped campaign 2 weeks ago - still within cooldown.

### 7.4 - Spam Check (NON-NEGOTIABLE before push)

**Run TWO checks, and block on either.** They catch different things and neither substitutes for the other:

| Check | Type | Catches | Misses |
|-------|------|---------|--------|
| **Word list** | Deterministic | Known trigger words, in every language you send in | Anything phrased in a way it does not have on file |
| **AI tone review** | Judgement | Salesy register, hype, pressure, register that reads like marketing | A specific banned word it does not consider spammy |

Tools for the word-list pass:
- **MCL Spam Word Checker** at [mycoldleads.com/spam-checker](https://mycoldleads.com/spam-checker) - free, real-time spam word database
- **Postmark SpamCheck API** - free SpamAssassin scoring
- Your own list, which compounds in value over time - add every new pattern you find

**Subject lines take the strict policy.** A word that is survivable in the body can sink a subject.

**If any variant has critical/high spam words, or scores 5+ on SpamAssassin, or fails the tone review: STOP. Fix the copy before pushing.**

For pre-computed custom fields (e2_body, e3_body), sample and check them programmatically - they are copy too, and they never went through the sequence editor where you would have noticed.

**Where variation actually helps.** Body variation matters as much as subject variation. In a side-by-side test with the same inboxes, subject, signature, unsubscribe line and validated list, the low-body-variation variant bounced at around 50% and the high-variation one did not. Vary the subject, signature and unsubscribe line too - but never treat repeated body copy as safe.

### 7.4b - Post-Spam Copy Grader (MANDATORY - second gate)

After spam checking and any spam-related rewrites, re-run the Copy Grader from 6.4b.

This catches issues introduced by spam word replacements (sometimes spam fixes make copy worse).

**Same self-iteration loop applies:**
1. Score the post-spam copy
2. If score < 80: auto-fix and re-score
3. If any anti-pattern introduced by spam fixes: address it
4. Must reach Excellent (80+) or 3 iterations before flagging the user
5. Report: "Post-spam Copy Grader: [score]/100. [any changes from pre-spam score]."

**If spam fixes degraded the score by >10 points:** flag this explicitly - it means the spam rewrites hurt more than they helped and need manual review.

### 7.5 - Campaign Final Check (pre-push)

Run a comprehensive final check against the generated data before pushing. All FAIL items are blocking. Check includes:
- All required custom fields populated (no empty, null, undefined, placeholder markers)
- proof_line_1 != proof_line_2 for every lead
- No domain normalization failures (fields where normalized_name is still a raw domain)
- No ALL CAPS values in fields used in subject lines
- No spintax in custom field values (spintax belongs in templates, not custom fields)
- If your template expects a bullet prefix, bullet fields start with it
- HTML fields have no `\n` between tags

### 7.6 - Full-Batch Validator Sweep (MANDATORY - last gate before push)

Run your validator against the ENTIRE push batch. This catches any violations that slipped through earlier gates (e.g., fields assembled from lookup tables that weren't AI-generated but still violate rules).

```
FINAL VALIDATION SWEEP
======================
Leads checked: {N}
Clean: {N} ({%})
Violations found: {N} ({%})

If violations > 0:
  [list top 5 violation types with counts]
  BLOCKING: Fix or remove violated leads before push.
```

**Zero tolerance at this gate.** Any lead with a violation is removed from the push set.

### 7.7 - Real-Email Review (HARD BLOCK - the pre-push gate)

**A synthetic example shows template structure. It does not show the emails you are about to send.** Review the real ones before the push, not on the live campaign after it - every fix spotted after a push forces a re-render and a re-push.

**Step 1 - Subject variants first.** Draft at least **10 subject variants per persona**: lowercase static text, variables outside spintax braces, each one passing the directory test (6.4). Put them at the **top** of the review, next to the live subject and a rendered example of each. They are approved together with the copy. Fewer than 10 per persona blocks the review from being built.

**Step 2 - Pull ~40-48 real cohort emails,** the exact copy queued for push, spread across persona and signal type so every route the renderer can take is represented.

**Step 3 - Render every email in full** through the live sequence template: greeting with the real first name, body, sign-off spintax, and `%signature%` resolved to the campaign's real inbox signature. A body-only dump is not reviewable. If the template fetch fails, the build fails - no silent body-only fallback.

**Step 4 - Show the approver.** Open the review so they can actually read it (a browser page, not a file path). They approve or list fixes.

**Step 5 - Lock approval to a fingerprint of the copy.** Store a hash of the approved copy (subjects plus the cohort's rendered fields) with the approver's own words. Before push, recompute the hash. **Any edit after approval changes the hash and needs re-approval.** "Approve, then quietly change a line, then push" must be impossible.

Run the opener-question fit, plain-language and singular-grammar checks from 6.4 before building this review, so the approver reads copy that has already passed them.

---

## PUSH APPROVAL GATE (NON-NEGOTIABLE)

**Before ANY data is sent to your sending platform, Claude MUST stop and show the user this summary, together with the real-email review from 7.7:**

```
PUSH PREVIEW - {CLIENT} {PERSONA} -> Campaign {ID}
============================================================
Contacts to push: {N}
Domain distribution: {top 5 domains with counts}
Subject variants for this persona: {N} (all shown at the top of the review)
Real emails in the review: {N}, rendered with greeting and signature
Copy fingerprint: {hash}

Are you happy with this? Type "push" to proceed, or describe what to fix.
```

**Do NOT call the push API until the user explicitly approves, and the copy fingerprint at push time matches the one they approved.**

If the user asks to fix something, apply the fix, rebuild the review and show it again. Do not push until approved.

This gate applies to every campaign in a multi-persona run - show one preview per campaign and wait for approval before pushing each one.

---

## Phase 8: Push to Sending Platform

**Push through the wrapper, never with a raw API call.** This repo ships one for Smartlead: `scripts/push-safe.py` (Python 3 standard library, plus `psycopg` only if it reads your outreach log straight from Postgres). Every push path - the main run, a top-up, a one-off recovery - calls it. The push-safe hook blocks raw calls to the leads endpoint.

```bash
# 1. Dry run (the default): shows who would be pushed, who is skipped and why. Nothing is sent or logged.
DATABASE_URL=postgres://... python3 scripts/push-safe.py \
  --campaign 1234567 --client ACME --campaign-name acme-2026-09-p2 --leads leads.csv

# 2. After the push approval gate and a fresh hardening proof (5.1): add --apply
SMARTLEAD_API_KEY=... DATABASE_URL=postgres://... python3 scripts/push-safe.py \
  --campaign 1234567 --client ACME --campaign-name acme-2026-09-p2 --leads leads.csv --apply

# No direct database access? Use a JSON export of your outreach log instead; --apply appends to it.
python3 scripts/push-safe.py --campaign 1234567 --client ACME --leads leads.csv --outreach-log outreach_log.json
```

What it does, in order: drops invalid emails and repeats of the same person, skips anyone inside the 90-day cooldown (`COALESCE(first_sent_date, loaded_date)`, so queued-but-unsent counts), forces the three settings below to false on every request, posts in batches of up to 1,000, reconciles each batch against `total_leads`, writes the outreach log row for each lead as its batch is accepted, persists one state line per batch, stops after two consecutive failed batches, and prints `attempted / succeeded / failed / skipped` with reasons. Add `--plan-out plan.json` to see the exact request bodies. If you use another platform, keep the same steps in your own wrapper and set `PUSH_SAFE_WRAPPER` to its name.

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

---

## Phase 9: AI Quality Review (NON-NEGOTIABLE - AI Subagent)

**This is a post-push second look, not the approval gate.** The gate is the real-email review in 7.7, before the push. This phase checks what actually landed on the platform.

**After pushing leads, run an AI subagent to review EVERY observation and custom field in the campaign. NEVER use regex scripts for this - AI catches orders of magnitude more issues.**

For each campaign, fetch all leads and spawn an AI review agent (use a fast, cheap model like Claude Haiku) with the full list. The agent must check every single lead for:

1. **Marketing language/slogans in observations** - superlatives, editorial opinions, promotional phrases that aren't factual
2. **Company name in observation** - template already includes {{company_name}}, so observation must never contain the company name or any variant
3. **Awkward phrasing** - "For a project like your..." reads badly; rephrase
4. **Too vague/generic** - "expanding operations" without any specific detail
5. **Too long** - observations over ~15 words
6. **Wrong format** - prefix in the observation field that belongs in the template
7. **Condescending/presumptuous tone** - anything implying the lead is failing
8. **company_name issues** - wrong casing, missing abbreviation
9. **Factual implausibility** - claims that seem wrong or confused

**CRITICAL: Review fields IN CONTEXT of the full email template, not in isolation.**

Fields like observations and bullets only make sense when rendered inside the actual E1/E2 email. An obs that looks fine alone may create double punctuation, awkward grammar, or tonal mismatch when placed in the template.

**Process:**
1. Fetch all leads with their custom fields from your sending platform
2. **Render the full E1 and E2 emails** for each lead using the campaign's actual templates
3. Spawn AI review agent with the **rendered emails** (not isolated fields)
4. Agent outputs a list of flagged leads with issue type and suggested fix
5. Fix all flagged leads
6. Push fixes
7. Re-run review on fixed leads to confirm clean

**Incident:** QA reviewing isolated fields missed that an observation ending with "." created double punctuation in the template. Only rendering the full email exposed the bug. hundreds of leads needed patching.

**Only proceed to Phase 10 (post-push verification) when the AI review agent returns zero issues.**

## Phase 10: Post-Push Verification

**After AI quality review passes, run a final check against live data in your sending platform (NON-NEGOTIABLE).**

Verify the same checks pass against actual stored lead data - not just the local file.

Update config:
- Campaign Roster: lead counts and status = LOADED
- Copy Status: LOADED
- Status & Next Move: "Ready for launch approval"

---

## Phase 11: Launch Gate

**This step requires explicit user approval. Do not proceed without it.**

State:
> "All [N] campaigns are loaded and verified. Pre-launch QA passed. To launch:
> - [Campaign 1]: X leads, domains [Y]
> - [Campaign 2]: X leads, domains [Y]
> Approve launch?"

**Before activating, re-verify deliverability hardening (Phase 5.1) one final time.** Read the campaign back from the API and confirm open tracking off, click tracking off, plain text on. Any settings change since Phase 5 - including something as innocent as a rename - can have silently reset plain text. Tracking becomes immutable the moment the campaign sends, so this is the last chance.

On approval:
1. Re-verify hardening (above). If it fails, fix and re-verify before going further.
2. Activate each campaign in your sending platform
3. Update config Campaign Roster: status = LIVE, launched date
4. Update Domain Health table: mark domains as PRIMARY
5. Update Status & Next Move: "Live since [date]. Monitor for first 24h."

---

## Phase 12: Post-Launch Monitoring

### 24h Check

Analyze campaign performance 24h after launch:
- Any bounce spikes (>3% = pause that domain immediately)
- Any early replies - categorize and respond
- Email delivery rate (if <95%, investigate sending infrastructure)

### Day 7 Check

Full analysis:
- Open rates, reply rates vs benchmarks
- Any domain health issues
- Compare to other campaigns for same client

### Day 14 Check

Full performance review. If reply rate <1%: full copy audit. If <0.5%: consider pausing and refreshing copy.

---

## Phase 13: Targeting Feedback Loop

**After 7-14 days of live data, close the loop by analyzing which targeting signals performed best.**

### 13.1 - Pull Positive Replies

Query your campaign responses to identify positive replies (interested, meeting booked, forwarded internally):

```sql
SELECT
  cv.signal_type,
  cv.observation,
  comp.personalization_data->>'industry' as industry,
  comp.personalization_data->>'employees' as employee_count,
  cr.reply_category,
  cr.reply_text
FROM campaign_responses cr
JOIN contacts c ON LOWER(c.email) = LOWER(cr.lead_email)
JOIN campaign_variables cv ON cv.contact_id = c.id AND cv.campaign_id = cr.campaign_id
JOIN companies comp ON comp.domain = SPLIT_PART(c.email, '@', 2) AND comp.client_name = '{CLIENT}'
WHERE cr.campaign_id IN ({campaign_ids})
  AND cr.reply_category IN ('interested', 'meeting_booked', 'forwarded_internally')
ORDER BY cr.created_at DESC;
```

### 13.2 - Analyze Winning Patterns

For each positive reply, document:
- **Signal type that triggered the observation** (expansion, hiring, partnership, etc.)
- **Industry/sector** of the responding company
- **Company size** (employee count)
- **Observation angle** that resonated (what specific fact was mentioned?)
- **Which email step got the reply** (E1, E2, E3?)

### 13.3 - Build Signal Performance Table

Illustrative example (made-up numbers):

```
SIGNAL PERFORMANCE - {CLIENT} - Campaign Batch [date]
=====================================================
| Signal Type | Sent | Replies | Reply Rate | Positive | Positive Rate |
|-------------|------|---------|------------|----------|---------------|
| expansion   | 200  | 10      | 5.0%       | 4        | 2.0%          |
| hiring      | 100  | 4       | 4.0%       | 1        | 1.0%          |
| partnership | 100  | 3       | 3.0%       | 1        | 1.0%          |
| generic     | 300  | 3       | 1.0%       | 0        | 0.0%          |
```

### 13.4 - Feed Back into Next Cycle

Based on the signal performance data:
1. **Double down on winning signals** - prioritize companies with top-performing signal types in the next push
2. **Deprioritize weak signals** - if `generic` consistently underperforms, invest more in research to find real signals rather than defaulting to generic
3. **Refine the observation prompt** - if a certain angle (e.g., hiring-related observations) gets 3x the reply rate, weight the prompt to prefer that angle when multiple signals are available
4. **Update the client config** with signal performance data for future reference
5. **Adjust TAM sourcing** - if one signal type performs well, source more companies that show it for the next batch

### 13.5 - Save Learnings

Update the client config with a table like this one. Illustrative example (made-up numbers):
```markdown
## Signal Performance (last updated: {date})
| Signal | Campaigns Tested | Avg Positive Rate | Notes |
|--------|-----------------|-------------------|-------|
| expansion | 3 batches | 2.0% | Best performer - prioritize |
| hiring | 3 batches | 1.0% | Strong second |
| generic | 3 batches | 0.5% | Avoid - invest in research instead |
```

This data compounds over time. After 3-4 cycles, you'll have statistically significant signal performance data that dramatically improves targeting quality.

---

## Phase 14: Run Retro (final step, every run)

**Phase 13 improves the targeting. This improves the pipeline.** Without it you fix the same problem every month and never notice.

At the end of every run, collect what actually deviated:
- Steps that were skipped, and the reason given
- Gates that failed and what it took to get them green
- Anything that needed a manual patch after a bulk step reported success
- Any incident logged during the run

Then answer three questions:

1. **What wasted the most time?** Usually not the thing that felt hardest at the time.
2. **What was the root cause?** A missing gate, a stale doc, a prompt that never got updated after the last fix.
3. **What is the smallest change that stops it recurring?**

**Apply the safe fixes immediately** - documentation, a new validation check, a clearer error message, an extra item on a checklist. These are cheap and they decay if deferred.

**Do not auto-apply anything that changes what gets sent or to whom.** Sending logic, dedup rules, cohort selection, prompts and copy all go to a human first. The retro proposes; it does not ship.

**Feed new failure patterns back into the prompts in the same session.** Every bulk run at scale surfaces 1-5% of edge cases the prompt did not anticipate. That is a property of scale, not a sign the prompt failed. Fix the records by hand, add the pattern to the banned list, and move on. Iterating a sixth time to catch the last 2% costs more than it saves.

---

## Reproducibility: Save a Manifest (NON-NEGOTIABLE final step)

**A campaign you cannot rebuild is a campaign you cannot debug.** Six weeks later someone asks why a lead got a particular email, and the answer has to be reconstructible from something other than memory.

At the end of every run, save one manifest recording:

| Pin | Why |
|-----|-----|
| Script paths **and their commit hashes** | "The renderer" is not a version. The renderer at commit `abc123` is. |
| Prompt IDs from your prompt library | The prompt has been iterated since. You need the one that ran. |
| The cohort table and its row count | So you can reconstruct exactly who was in scope |
| **Verbatim** sequence templates and subjects | Not a path to them. The text. Templates get edited. |
| Gate evidence | Which checks passed, when, with what result |
| Campaign IDs and the send configuration | Inboxes, schedule, settings as they were at launch |

**Then verify the manifest resolves, rather than trusting that you wrote it correctly.** Re-read it and check each pin still works: the scripts exist at those commits, the prompt IDs return rows, the cohort table count still matches, the saved templates still match what is live on the platform. A manifest full of stale pointers looks exactly like a good one until the day you need it.

This replaces "read the local cache files and hope", which is what the old recovery section said and which fails the moment `tmp/` is cleaned.

---

## Context Window Survival

If context resets mid-production:
1. Read the manifest and gate evidence for this run - that is the structural record of where you got to
2. Check your database for what actually persisted: research on companies, variables on contacts, outreach log rows. Per-record persistence (Phase 4.3, 6.8) means this is the real progress marker, not a guess.
3. Check the local cache and results files from 4.2 and 6.7 if they still exist - convenience only, never the source of truth
4. Resume from the last phase whose gate evidence exists

**Keep chronological state out of your config markdown.** "What happened and when" belongs in a queryable store - the push log, the gate evidence, a comments table on the project. The config file is for reference data: ICP, lookup tables, template paths, persistent IDs. Mixing the two produces a file that is both the plan and the diary, and it goes stale silently while still looking authoritative.

---

## Sending Platform Push Gotchas (Smartlead-specific, adapt for your platform)

1. **`.join('\n')` causes double spacing** - ALWAYS `.join('')` for HTML arrays
2. **Spintax doesn't resolve in custom fields** - pre-resolve before pushing
3. **`<div>{{body_var}}</div>` adds extra wrapping** - if the custom field already contains `<div>` tags, the template should be just `{{body_var}}` with no wrapping div
4. **Max 200 custom fields per lead** - Smartlead hard limit
5. **Empty custom fields render as blank** - `{{missing_field}}` becomes empty string, causing double spaces or trailing periods
6. **Bullet prefix** - if your template expects a bullet prefix, prepend it to every bullet field value before pushing
7. **NEVER put variables inside spintax braces** - `{Hello {{first_name}}|Hi {{first_name}}}` BREAKS Smartlead

## Sequence API Rules (if also loading sequences via Smartlead)

1. **`seq_variants` NOT `sequence_variants`** for POST - they use DIFFERENT field names for read vs write
2. **ALWAYS include `id` for existing sequences** - missing `id` = creates NEW records, orphaning analytics permanently
3. **Wrap delay**: `seq_delay_details: { delay_in_days: N }` - NOT flat `delay_in_days`
4. **Body wrapper**: `{ "sequences": [...] }` - bare array = 400 error
5. **For A/B variants**: BOTH must be in `seq_variants` array - putting A only in base `email_body` = B never sends
6. **Sequence IDs != variant IDs** - passing variant IDs as `id` deletes everything

---

## Automation Path

This skill should eventually become automated workflows:
1. Phases 1-4: Automated workflow triggered by webhook (TAM check + research + normalization)
2. Phase 6: AI generation nodes + code nodes (variable generation at scale)
3. Phase 7: Validation workflow with Slack/alert on failures
4. Phase 11: User approves via Slack button or similar, workflow activates campaigns
5. Phase 13: Automated weekly signal performance reports feeding back into targeting

### Every unattended job needs a circuit breaker (NON-NEGOTIABLE)

The moment a phase runs without someone watching, its failure mode changes. Supervised, a crash is an inconvenience. Unsupervised with a default restart policy, a crash becomes a loop.

**One crash can be transient. A second consecutive crash means stop everything. There is no third retry.**

1. Count consecutive failures in storage that survives a restart - a database row or a KV flag. Never a variable in the process, which resets to zero on every restart and makes the counter useless precisely when you need it.
2. Check the counter before the risky operation, at startup. If tripped, exit cleanly with a success code and log loudly - a crash-on-startup is itself a restartable event.
3. Set the platform's restart policy to never, or at most one retry. The common default is ten.
4. Clearing the breaker requires a human. Never auto-clear after N hours.

**Why the second crash is the line:** auth failures, rate limits and spend all compound on retry. Each restart makes the situation worse rather than better. Ours retried a third-party login five times in ninety seconds and got the account session invalidated. The account survived. A less forgiving service would have locked it permanently or drained the budget.

This applies to every scheduled thing you build: cron workers, AI generation loops, the email waterfall, bulk pushes, anything on a timer.
