<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

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

### 2.2b - Personal Email Addresses (per-client rule)

Whether to mail personal mailboxes (gmail.com, outlook.com and similar) is a client decision, not a global one. For a client selling to large companies a personal address on a decision maker is an anomaly worth excluding. For a client selling to very small businesses it is normal and excluding it throws away real buyers.

Read `exclude_personal_emails` from the client config (section 14). Default: off. When it is on, drop those contacts here and pass `--exclude-personal-emails` to the wrapper so the same rule is enforced at push time. Extend the built-in domain list for your market with `--freemail-domains FILE`. Never exclude on a personal address alone when the rule is off.

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
