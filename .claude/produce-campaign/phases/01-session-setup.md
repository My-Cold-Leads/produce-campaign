<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

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

### 1.1a - Campaign Type

Read `campaign_type` from the campaign config: `prospect` (default) or `partner`. A partner campaign writes to people you want to sell *with* (resellers, integrators, distributors), not *to*. It skips the steps that only make sense for prospects (per-company news observation, customer social proof, ICP-fit scoring) and keeps every safety gate unchanged: suppression, email status, cooldown, copy variation, hardening, real-email review, approval. Do not improvise other types; an unknown value means ask.

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

### 1.2c - Cohort Ledger (HARD GATE, instruction-only)

Keep one ledger per run (`cohort-ledger.json` next to the run's other files) and add a row every time the cohort changes size:

```json
{"stage": "2.2 quality filters", "in": 1840, "out": 1512, "removed": {"email_status_not_verified": 301, "dnc": 27},
 "source": "query or file that produced these numbers", "at": "2026-11-20T10:14:00Z"}
```

Rules:

1. **No stage starts without the previous stage's row.** Its `in` must equal the previous `out`. A gap means leads vanished without a reason: stop and find them.
2. **Every removal has a named hard reason and a source.** "Looked weak", "low priority" and "kept the best ones" are soft cuts. A soft cut needs the user's explicit yes, recorded in the row.
3. **Agree a target with the user at the start and write it in the first row.** If the cohort falls below the target at any stage, stop and show the whole funnel from the ledger. Do not continue with a short cohort and mention it at the end.
4. The numbers in the push preview and the final report are read from the ledger, never from memory.

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
