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

Do not proceed to the next phase until the user says yes. The user may approve a named run of phases up front ("run Phases 2 to 4"); inside that run, report each phase result and continue. An up-front yes never covers three things, which each need their own yes every time: a paid run's cost estimate (6.5), the push approval gate, and the launch gate (Phase 11).

### What is enforced by code, and what is an instruction

Most gates in this document are instructions to you. A small set is also enforced by code that ships in this repo, and will refuse the action whatever you intend:

| Enforced by | What it refuses |
|---|---|
| `scripts/push-safe.py` | Duplicates, suppressed contacts and company domains, unverified email statuses, prior positive / wrong-person replies (database mode), cooldown, missing merge fields, an unsigned or mismatched approval, a campaign that does not match the client, leads already queued or recently sent elsewhere on the platform, suppression settings switched off |
| `scripts/verify-hardening.py` + hardening hook | Starting a campaign or loading leads without a fresh proof for that exact campaign (tracking off, plain text on, no campaign-level gap, agreed follow-up percentage) |
| `scripts/check-copy-variation.py` | A body line in more than 15% of emails, a fixed line, fewer than 90% distinct emails |
| Hooks in `.claude/hooks/` | Raw lead pushes (shell, script or MCP tool), the abstention token in a push, spintax or `%signature%` inside a custom field, uncached model loops, buffered writes of paid results |

Everything else, including research quality, source-quote checks, the offer gate, the cohort ledger and the real-email review itself, depends on you following the text. Do not describe an instruction-only gate to the user as "enforced".

---

## How this skill is laid out (read this first)

This file holds the rules that apply to every phase and the index. Each phase lives in its own file under `.claude/produce-campaign/phases/`, so you only carry the phase you are working on.

**Before starting a phase, read its file in full. After a context reset, read it again; do not work from memory of an earlier read.** Section numbers (for example "6.4" or "7.7") keep their meaning across files: the first number is the phase.

| Phase | File | Read it |
|---|---|---|
| Phase 0: TAM creation | `.claude/produce-campaign/phases/00-tam-creation.md` | First run for a client, or when the TAM is rebuilt |
| Phase 1: session setup, pacing, cohort ledger | `.claude/produce-campaign/phases/01-session-setup.md` | Start of every session |
| Phase 2: contact selection | `.claude/produce-campaign/phases/02-contact-selection.md` | Before selecting the cohort |
| Phase 3: email validation | `.claude/produce-campaign/phases/03-email-validation.md` | Before any verification spend |
| Phases 4 and 4.5: company data and website identity | `.claude/produce-campaign/phases/04-company-data.md` | Before research and normalization |
| Phase 5: campaign infrastructure and hardening | `.claude/produce-campaign/phases/05-infrastructure.md` | Before creating or configuring campaigns, and again before launch |
| Phase 6: offer gate and variable generation | `.claude/produce-campaign/phases/06-variable-generation.md` | Before writing any prompt or copy |
| Phase 7 and the push approval gate | `.claude/produce-campaign/phases/07-prepush-validation.md` | After generation, before any push |
| Phase 8: push | `.claude/produce-campaign/phases/08-push.md` | Only after the push approval gate |
| Phases 9 to 11: post-push review, verification, launch gate | `.claude/produce-campaign/phases/09-review-verify-launch.md` | Straight after the push |
| Phases 12 to 14 and the run manifest | `.claude/produce-campaign/phases/12-after-launch.md` | After launch, and at the end of every run |
| Smartlead push and sequence API gotchas | `.claude/produce-campaign/phases/reference-smartlead.md` | Before any call to the sending platform API |
| Automation path and circuit breakers | `.claude/produce-campaign/phases/reference-automation.md` | Before moving any phase onto scheduled infrastructure |

Order of work: 0 (first time only), 1, 2, 3, 4, 4.5, 5, 6, 7, push approval gate, 8, 9, 10, 11, 12, 13, 14, manifest. Phase 5 must be complete (sequences loaded) before Phase 6 starts.

---

## Context Window Survival

If context resets mid-production:
1. Read the manifest and gate evidence for this run - that is the structural record of where you got to
2. Check your database for what actually persisted: research on companies, variables on contacts, outreach log rows. Per-record persistence (Phase 4.3, 6.8) means this is the real progress marker, not a guess.
3. Check the local cache and results files from 4.2 and 6.7 if they still exist - convenience only, never the source of truth
4. Resume from the last phase whose gate evidence exists

**Keep chronological state out of your config markdown.** "What happened and when" belongs in a queryable store - the push log, the gate evidence, a comments table on the project. The config file is for reference data: ICP, lookup tables, template paths, persistent IDs. Mixing the two produces a file that is both the plan and the diary, and it goes stale silently while still looking authoritative.
