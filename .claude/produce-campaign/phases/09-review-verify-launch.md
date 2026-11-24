<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

## Phase 9: AI Quality Review (NON-NEGOTIABLE - AI Subagent)

**This is a post-push second look, not the approval gate.** The gate is the real-email review in 7.7, before the push. This phase checks what actually landed on the platform.

**After pushing leads, run an AI subagent to review EVERY rendered email in the campaign.** This is a judgement review (tone, plausibility, fit in context), so a model does it. The deterministic checks (variation, banned words, empty fields) already ran before the push and are not repeated by eye here. The campaign is still a draft: nothing has been sent.

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
5. **Do not edit a lead on the platform.** The copy there is the approved copy (7.7); changing it would send something nobody approved, and the push hook blocks update calls to the leads endpoint for that reason.
6. For each flagged lead: with the user's OK, remove it from the draft campaign, fix it in your database, and hold it for the next push, where it goes through 7.7 and the wrapper again. Its outreach log row stays, which is correct: it was loaded.
7. If more than 2% of the push is flagged, the pre-push review failed. Stop, tell the user, and with their OK remove the batch from the draft campaign and go back to 6.3. Do not launch around it.
8. Record the flagged patterns in the prompt's banned list so the next run catches them before the push.

**Incident:** QA reviewing isolated fields missed that an observation ending with "." created double punctuation in the template. Only rendering the full email exposed the bug. hundreds of leads needed patching.

**Only proceed to Phase 10 (post-push verification) when every lead still in the campaign has passed the review.**

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
1. Re-verify hardening with `python3 scripts/verify-hardening.py --campaign <id> --follow-up-percent <agreed value>` for each campaign. If it fails, fix and re-verify before going further. The hook refuses the activation without that campaign's fresh proof.
1b. Cite the DNS receipt and the link receipt for the send set (5.1b). No receipt, no launch.
2. Activate each campaign in your sending platform
3. Update config Campaign Roster: status = LIVE, launched date
4. Update Domain Health table: mark domains as PRIMARY
5. Update Status & Next Move: "Live since [date]. Monitor for first 24h."
