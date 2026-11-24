<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

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

**APPROVED statuses: `valid` and `deliverable_catchall` ONLY.** (`scripts/push-safe.py` enforces this at push time; it also accepts `verified` for verifiers that use that word. Change the list with `--allow-status` only with the user's OK.)

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

**Check BOTH contact-level and company-level DNC.** `scripts/push-safe.py` enforces both at push time (database flags, or the `--suppression` file in file mode), including subdomains. Run the queries below earlier anyway, so the push preview shows real numbers.

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

Note: the cooldown works on send history, so it also covers people whose sequence finished on a campaign that is now completed or stopped. `scripts/push-safe.py` applies it on every push, then asks the platform itself (7.3c) about anything your log missed.

### 7.3c - Live Platform Membership (HARD GATE, in the wrapper)

Your outreach log only knows about pushes that went through the wrapper. A lead added in the platform UI, by a raw API call or by a colleague's script is invisible to it, and a push in that window emails the same person twice.

So before every push, `scripts/push-safe.py` asks the platform where each address already is, within the same platform client as the target campaign, and skips the lead when:

- it was **sent from another campaign inside the cooldown window**, or
- it sits **unsent in another campaign that is not finished** (it would be mailed in parallel), or
- the platform has it **unsubscribed**.

A lookup that fails after retries skips that lead: an unverifiable lead is not a safe lead. There is no flag to turn this off. It runs on every `--apply`, and on a dry run when you pass `--live-check`.

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

**Step 5 - Lock approval to a fingerprint of the copy.** Run the wrapper's dry run with `--template` and `--write-approval-request approval.json`. That file holds a hash of the template and a hash of every lead's exact payload. Only after the approver says yes, fill `approved_by` (their name) and `approved_at`, and keep their own words in `note`. At push time the wrapper recomputes every hash: **a lead that was edited or added after approval, or a changed template, stops the push.** The approved set may shrink (a lead dropped by a later gate needs no new approval). There is no path that edits copy after approval without a new review, including the post-push phases below.

The wrapper proves the push set is the reviewed set. It cannot prove who typed the name into the file, so never fill `approved_by` yourself before the user has approved in their own words.

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
Approval file: approval.json ({N} lead hashes + template hash), unsigned until you approve

Are you happy with this? Type "push" to proceed, or describe what to fix.
```

**Do NOT run the wrapper with `--apply` until the user explicitly approves.** Then sign the approval file with their name, the time and their words. The wrapper refuses `--apply` without a signed approval whose hashes match what is being pushed.

If the user asks to fix something, apply the fix, rebuild the review and show it again. Do not push until approved.

This gate applies to every campaign in a multi-persona run - show one preview per campaign and wait for approval before pushing each one.
