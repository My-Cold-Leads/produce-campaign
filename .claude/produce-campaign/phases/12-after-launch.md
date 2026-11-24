<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

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
