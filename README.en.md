# Cold Email Campaign Production Pipeline

This is the exact campaign production pipeline we use at our cold email agency to take a client from zero to launched campaign. It's a Claude Code skill - meaning you install it, type `/produce-campaign`, and Claude walks you through every step.

## Why we're sharing this

There's too much vague advice about cold email and not enough real playbooks. "Just personalize your emails" doesn't tell you how to do it at scale without destroying your domain reputation or sending garbage.

We built this pipeline from running real campaigns for real clients. Every quality gate exists because something broke without it. Every validation step exists because we once skipped it and paid the price - wrong data sent to leads, domains burned, campaigns killed by spam filters.

We're sharing it because we think the industry gets better when people stop guessing and start following a process. We hope it saves you the same pain it saved us.

## Who this is for

**You've never run a cold campaign.** You have a product or service, you know who you want to reach, but you've never built a list, written a sequence, or pushed leads to a sending platform. This skill guides Claude Code to walk you through the entire process step by step - from finding companies to monitoring your first replies.

**You already run campaigns.** You want to see how an agency structures production at scale. The quality gates, validation layers, and feedback loops in this pipeline might give you ideas for your own process.

## What you'll need

This is a real production stack, not a toy. You'll need accounts with these tools:

| Tool | What it does | Required? |
|------|-------------|-----------|
| [Claude Code](https://claude.ai/code) | Runs this skill - your AI copilot for the entire process. We recommend the $100/month Max plan as a minimum - this pipeline is intense and will burn through usage on lower tiers. | Yes |
| [Smartlead](https://smartlead.ai) | Sends your emails, manages sequences, tracks replies | Yes |
| [Supabase](https://supabase.com) | Stores your companies, contacts, and campaign data (free tier works) | Yes |
| [Serper](https://serper.dev) | Researches companies via Google search (cheap - $0.003/search) | Yes |
| A small LLM (GPT-4o-mini class, or Claude Haiku for tone-sensitive copy) | Variable generation and quality review. Default to the cheapest capable model, pin it per prompt and show a cost estimate before paid runs; see CLAUDE.md before reaching for a bigger one. | Yes |
| [MillionVerifier](https://millionverifier.com) | Email verification | Recommended |
| [BounceBan](https://bounceban.com) | Catchall verification - confirms an individual mailbox exists on a catchall domain | Recommended |

### Finding contacts: the order matters more than the tool

Contact tooling splits into two jobs that people conflate, and getting them the wrong way round is expensive.

| Job | What you have | What you want | Go here first |
|-----|--------------|---------------|---------------|
| **Discovery** | A company | A list of decision makers at it | [Apollo](https://apollo.io). Its people search is free. Filter to the ones with emails, dedupe against what you already hold, and only then pay to enrich the unknowns. |
| **Enrichment** | One named person | Their verified email | [Prospeo](https://prospeo.io). Same per-credit cost as the alternatives but free re-enrichment and free on a miss, so it amortises cheaper. |

Fall back to [Icypeas](https://icypeas.com) or [Findymail](https://findymail.com) as extra waterfall providers when your first choice misses.

**For discovery, run five sources at once over the whole list:** Prospeo, Apollo, AI search on Google (role-targeted queries that Claude reads and verifies), the company's own website, and local or niche databases (sector directories, trade fair and event exhibitor lists). Filter only by the country the person works in, never by job title, and let AI classify the titles afterwards. The full method is in phase 0.3 of `.claude/commands/produce-campaign.md`.

Running a paid search-first tool in the discovery slot cost us roughly 4x what it should have, because most of the spend went on people already in our database. Free search, then dedupe, then pay.

**Do not re-run discovery on the same company list inside 90 days.** It returns about 5% new finds at full price.

**Starting with the minimum?** Claude Code + Smartlead + Supabase + Serper + Apollo covers sending, storage, research and contact finding. Add a verifier before you send to anyone.

### What this covers

This is an **email-only** pipeline. LinkedIn and other outreach channels are not included; LinkedIn appears only as a data source for finding people. The sending side is written for **Smartlead**, the agent side for **Claude Code**, and the examples are in Spanish. Everything here - the sequence structure, the copy length, the per-company recipient cap, the cooldowns - assumes email and a receiving mail server.

If you add another channel later, the parts that do not transfer are: the per-company cap (a mail-server constraint, not a rule of outreach), message length norms, and the dedup rules, since a person can legitimately be in an email cohort and a social cohort at different times. Decide the channel up front rather than bolting it on, because almost every phase branches on it.

### Spam checking

The pipeline includes a spam check phase before every push. Instead of building your own spam word database, you can use our free [MCL Spam Word Checker](https://mycoldleads.com/spam-checker) - a real-time updated database of spam trigger words sourced from multiple providers. The skill references this tool at the spam check step.

## How to install

**You need:** Claude Code, Python 3.9 or newer, a Smartlead account and API key, and a Postgres database (Supabase works) or, for a first try, plain JSON files. `psycopg` is only needed if the push wrapper reads Postgres directly (`pip install psycopg`). No other dependencies.

1. Clone this repo (or download the files).
2. Copy the whole `.claude/` directory into your project root. It holds the command (`.claude/commands/`), the phase files it reads (`.claude/produce-campaign/phases/`), and the hooks with their tests (`.claude/hooks/`). If you already have a `.claude/` directory, merge it in rather than replacing it.
3. Copy `scripts/`, `prompts/` and `setup/` into your project root.
4. Copy `CLAUDE.md` to your project root (or merge it into your existing CLAUDE.md).
5. Turn the hooks on: merge the entries from `.claude/settings.example.json` into your `.claude/settings.json`. Add the entries inside the arrays rather than replacing the file. Hooks do nothing until this step is done.
6. Run the SQL in `setup/schema.sql` in your database. It is safe to re-run and it upgrades an older install. If the unique index on `contacts` fails, you already have duplicate contacts: the comment above that statement shows how to find them.
7. Set `SMARTLEAD_API_KEY` (and `DATABASE_URL` if you use Postgres) in your shell environment. Never write keys into a file in the repo.
8. Check the install. All four should end with `failed 0` or `failed=0`:
   ```bash
   bash .claude/hooks/tests/run-tests.sh
   python3 scripts/tests/test-push-safe.py
   python3 scripts/tests/test-verify-hardening.py
   bash scripts/tests/test-check-copy-variation.sh
   ```
9. Copy `setup/campaign-config.template.md` once per client and fill it in, including section 14 (sending settings) and section 15 (offer scorecard).
10. Open Claude Code and type `/produce-campaign YourCompanyName`.

Claude then walks you through each phase and stops for your approval at the gates.

## How it works

The pipeline has 14 phases. Each phase ends with a check, and Claude stops for your approval before moving on. A few of those checks are enforced by code; most are instructions Claude follows. See "What is enforced by code, and what is not" below.

1. **Session Setup** - Load your client config, check TAM health, verify data freshness
2. **Contact Selection** - Pick contacts by persona, apply quality filters, score the list, deduplicate
3. **Email Validation** - Find and verify email addresses through a provider waterfall
4. **Company Data Prep** - Normalize company names, research companies, confirm the website belongs to the company, persist data
5. **Campaign Infrastructure** - Set up campaigns in Smartlead, assign domains, load sequences, harden deliverability settings
6. **Variable Generation** - Generate personalized observations, bridges, bullets using AI
7. **Pre-Push Validation** - Spam check, DNC check, cross-campaign dedup, quality sweep, and a review of ~40-48 real, fully rendered emails that must be approved before the push
8. **Push to Smartlead** - Load leads with custom fields through the push-safe wrapper, verify counts, log the outreach
9. **AI Quality Review** - Haiku subagent reviews every rendered email, not just the fields
10. **Post-Push Verification** - Final check against live Smartlead data
11. **Launch** - Activate campaigns (requires your explicit approval)
12. **Post-Launch Monitoring** - 24-hour, day-7 and day-14 checks on bounces, replies and delivery
13. **Targeting Feedback Loop** - Analyze positive replies to sharpen future targeting
14. **Run Retro** - Capture what went wrong this run and fix the pipeline, not just the campaign

Every phase reports its results and asks before proceeding. The pipeline is designed to catch problems early - before they reach your leads' inboxes.

The gates that will feel like overkill until the first time they save you: the real-email review before push (Phase 7), the abstention contract that lets the AI say "I don't know" instead of inventing (Phase 6), and confirming the website you researched actually belongs to the company you are emailing (Phase 4).

## A note on quality

This pipeline is opinionated. It will stop you from pushing bad data, skipping steps, or launching without validation. That's by design.

Cold email done badly hurts your domain, your reputation, and the industry. Done well, it's the most efficient way to start conversations with people who need what you sell.

The quality rules in this pipeline (grade 5 reading level, bar conversation test, banned corporate jargon, single data point observations) come from running real campaigns for real clients and measuring what happened: what got replies and what got marked as spam.

## Scaling beyond Claude Code

Claude Code is the right place to **design, test, and iterate** on this pipeline. It is not the right place to run it manually 52 weeks a year.

Each of the 14 phases above is an n8n-workflow-ready building block - a single-responsibility step with a clear input and output. Once you've run the pipeline manually enough times that the prompts are stable and the outputs are predictable, graduate each phase to your scheduled infrastructure:

- **n8n / Make** - for workflow orchestration between phases
- **Railway / Fly / Modal** - for long-running scripts (Phase 3 email waterfalls, Phase 6 variable generation)
- **cron / pg_cron / Inngest** - for the recurring ops work (new-lead push cadence, weekly audit, quarterly retro)
- **Supabase** - already where your state lives; the phases read + write here

The pattern:

```
Claude Code          = design + test + iterate + escalate
n8n / Railway / cron = execute + schedule + scale
```

You keep the skill in Claude Code for the next round of iteration. You stop running it by hand on Monday morning. If you never graduate the pipeline, you become the bottleneck - every campaign production run is a week you could have used for strategy, client conversations, or sleep.

**Don't graduate until:** your prompts have passed two consecutive zero-edit test rounds (see the 10-example test loop in the skill), you've run the full pipeline manually at least 3 times with consistent output, and you can describe each phase's failure modes. Automating a broken pipeline just scales the brokenness.

**When you do graduate, add a circuit breaker to every unattended job.** One crash can be transient. A second consecutive crash means stop everything, and no third retry. Count the failures somewhere that survives a restart, check the count before the risky call, and make a human clear it. Set the platform's restart policy to never or at most one retry; the usual default is ten. Auth failures, rate limits and spend all compound on retry, so each automatic restart makes the situation worse rather than better. Ours retried a third-party login five times in ninety seconds and got the account session invalidated.

## Example prompts

The `prompts/` directory includes starter prompts for:
- Company name normalization
- Observation generation (personalized opening lines)
- Bridge sentences (connecting your observation to your offer)

These are starting points. You'll iterate them for your specific ICP and offer. The skill guides you through a test loop (10 examples -> feedback -> iterate -> validate on 50 -> production) to make sure your prompts are solid before running at scale.

## Language

This skill was built for Spanish-language campaigns. All examples and banned word lists are in Spanish. The methodology and pipeline structure work in any language - you'll just need to adapt the copy rules, banned words, and example prompts for your target language.

The copy variation check skips greeting, sign-off and unsubscribe lines using Spanish and English patterns. For another language, pass your own with `--exclusions`, as a JSON file or inline. Any key you leave out keeps its default:

```bash
python3 scripts/check-copy-variation.py --rendered rendered.json --client ACME \
  --exclusions '{"greeting": "^(bonjour|salut)\\b[^.!?,]{0,30}$", "signoff": "^(cordialement|bien à vous)$", "unsubscribe": "désinscri"}'
```

## What is enforced by code, and what is not

Be clear about what you are installing. This repo is a detailed runbook, plus a small amount of code that enforces the rules where a mistake cannot be undone. Most of the gates in the skill are instructions that Claude follows; they are not programs.

### Enforced by code that ships here

| Rule | Enforced by |
|---|---|
| Same person twice in one push | `scripts/push-safe.py` |
| Suppressed / do-not-contact address or company domain (subdomains included) | `scripts/push-safe.py` |
| Email status not in the verified list | `scripts/push-safe.py` |
| Person already replied interested / wrong person / left the company (database mode) | `scripts/push-safe.py` |
| 90-day cooldown, counting queued-but-unsent leads | `scripts/push-safe.py` |
| Lead missing a merge field the template uses | `scripts/push-safe.py --template` |
| Push set or template changed after approval | `scripts/push-safe.py --approval` |
| Campaign does not match the client, or the client name has no history | `scripts/push-safe.py` |
| Lead already queued in another live campaign, sent recently, or unsubscribed on the platform | `scripts/push-safe.py` (live membership check) |
| Personal mailboxes, when the client rule is on | `scripts/push-safe.py --exclude-personal-emails` |
| Platform suppression lists switched off | `scripts/push-safe.py` + push hook (no bypass) |
| Raw lead push that skips the wrapper | push hook |
| Campaign start or lead load without a fresh hardening proof for that campaign | `scripts/verify-hardening.py` + hardening hook |
| Campaign-level gap set, follow-up percentage not the agreed value | `scripts/verify-hardening.py` |
| A body line in more than 15% of emails, a fixed line, under 90% distinct | `scripts/check-copy-variation.py` |
| `NOT_FOUND` token in a lead payload; spintax or `%signature%` inside a custom field | hooks |
| Uncached model loop; paid results buffered and written at the end | hooks (heuristics) |

### Instructions only (Claude is told to do it; nothing stops a skipped step)

TAM pacing and the cohort ledger, the offer / value-equation gate, the in-flight check, research source-quote checks and address anchoring, the ICP check, the website identity check (4.5), the email-belongs-to-this-business check (3.5), greeting name confirmation, the sequence structure lock, the prompt iteration ladder, the copy grader, the spam check, the full-batch sweep, the real-email review page (the approval *file* is checked by code, building and reading the review is not), the DNS and link receipts before launch, post-push review, monitoring and the retro.

### Described but not shipped (you build these, or let Claude write them per run)

The email finding and verification waterfall, the company research agent, the ICP classifier, the email renderer (template + fields + spintax + signature), the field validator, the copy grader, the spam checker client, the review page builder, the sequence lock comparer, the sync job that fills `first_sent_date` and `campaign_responses` from your platform, prompt library tooling, and the manifest writer. Only three starter prompts ship in `prompts/`.

Two of those matter for the code that does ship: without a sync job, `first_sent_date` stays empty (the cooldown then runs on `loaded_date`, which is safe but conservative) and `campaign_responses` stays empty (the prior-reply gate and the in-flight check then pass everyone; the wrapper's live membership check still catches leads queued elsewhere).

**Realistic effort:** a team already on Claude Code, Smartlead and Postgres can adopt this in one to two weeks. Another agent framework or sending platform means rebuilding the wrapper and the hooks, using the skill as the spec.

### What the hooks can and cannot see

Hooks are PreToolUse checks that refuse a tool call. With the matchers in `.claude/settings.example.json` they inspect:

- **Bash** commands,
- **Write / Edit / MultiEdit** content,
- **MCP tool calls** (matcher `mcp__.*`: tool name and full input). Narrow the matcher to your sending platform's server if you prefer.

A tool that no matcher routes to them is not checked. They are pattern guards, not a sandbox: a push hidden inside a script whose source the hook never sees can get past them, which is why the wrapper repeats the important checks itself.

| Hook | Refuses |
|---|---|
| `pretooluse-push-safe-required.sh` | Switching off the platform's suppression list (never bypassable), and lead pushes that skip `scripts/push-safe.py`, from the shell, a script or an MCP tool. Any script named `push-safe.*` is trusted |
| `pretooluse-deliverability-hardening.sh` | Starting a campaign or loading leads without a proof for **that exact campaign**, written by `scripts/verify-hardening.py` in the last 120 minutes. A proof for another campaign, an empty file, or a call whose campaign id cannot be read is refused. Pausing never needs a proof |
| `pretooluse-custom-field-syntax.sh` | Spintax, signature tokens, or a variable nested inside spintax, in a custom field value |
| `pretooluse-abstention-guard.sh` | The `NOT_FOUND` abstention token reaching a payload bound for a lead |
| `pretooluse-prompt-cache-guard.sh` | A loop of LLM calls with no `cache_control` on the system block. Anthropic-specific by default (`LLM_ENDPOINT_RE`); OpenAI caches long prefixes automatically |
| `pretooluse-durable-writes.sh` | A loop that spends money per record and writes only at the end |

**Fail closed.** If a hook cannot parse the tool call it was given, it blocks.

### Bypass markers

Each hook except the suppression-list rule accepts a one-off marker in the command: `PUSH_SAFE_OK:`, `HARDENING_OK:`, `CUSTOM_FIELD_OK:`, `ABSTENTION_OK:`, `CACHE_OK:`, `DURABLE_WRITES_OK:`, followed by a reason of at least 10 characters. The reason, tool and time are appended to `.claude/<hook>-bypass.log`; a marker without a reason is blocked.

A marker is an audit trail, not a control: the agent being guarded can type one. Read the logs, and if you do not want markers at all, set `CAMPAIGN_HOOKS_NO_BYPASS=1`. Likewise the approval file proves the push set is the reviewed set, not that a person signed it. Keep a human on the approval.

### Prove they work before you trust them

```bash
bash .claude/hooks/tests/run-tests.sh            # 65 hook fixtures
python3 scripts/tests/test-push-safe.py          # 39 wrapper checks against a fake platform, no network
python3 scripts/tests/test-verify-hardening.py   # 10 checks
bash scripts/tests/test-check-copy-variation.sh  # 19 fixtures
```

Each gate is fed a known-bad input it must refuse and a known-good input it must allow. A gate that has never gone red might be working, or might be silently doing nothing. There is no CI in this repo; run them yourself after every change.

They are plain bash and Python with no dependencies. Read them; they are short.

### The push wrapper

`scripts/push-safe.py` is the one sanctioned way to load leads into Smartlead. It is a dry run unless you pass `--apply`, and `--apply` needs a signed approval file. Run `python3 scripts/push-safe.py --help` for the full list of gates.

```bash
# dry run: who would be pushed, who is skipped and why; writes the approval request
python3 scripts/push-safe.py --campaign 12345 --client ACME --leads leads.csv \
  --outreach-log outreach_log.json --suppression suppression.txt \
  --template e1.html --write-approval-request approval.json
# after the reviewer signs approval.json, and verify-hardening.py has passed for campaign 12345
SMARTLEAD_API_KEY=... python3 scripts/push-safe.py --campaign 12345 --client ACME --campaign-name "ACME E1" \
  --leads leads.csv --outreach-log outreach_log.json --suppression suppression.txt \
  --template e1.html --approval approval.json --apply
```

### Environment variables

| Variable | Used by | Default | What it does |
|---|---|---|---|
| `SMARTLEAD_API_KEY` | `scripts/push-safe.py --apply`, `scripts/verify-hardening.py`, `scripts/check-copy-variation.py --campaign` | none | Your Smartlead API key |
| `DATABASE_URL` | `scripts/push-safe.py` | none | Postgres connection string for the `outreach_log` table (cooldown read, push-time write). Use `--outreach-log FILE.json` instead if you have no direct database access |
| `PUSH_SAFE_WRAPPER` | push-safe hook | `push-safe` | Base name of your push wrapper, if you renamed it or wrote your own |
| `CAMPAIGN_HOOKS_NO_BYPASS` | all hooks | unset | Set to `1` to switch every bypass marker off |
| `CAMPAIGN_STATE_DIR` | hardening hook, `scripts/verify-hardening.py` | `.claude/campaign-state` | Where hardening proofs are written and read |
| `CAMPAIGN_HOOK_LOG_DIR` | all hooks | `.claude` | Where bypass audit logs are written |
| `HARDENING_MAX_AGE_MIN` | deliverability hardening hook | `120` | Minutes a hardening proof file stays valid |
| `ABSTENTION_TOKEN` | abstention hook | `NOT_FOUND` | The token your prompts return when the source does not support an answer |
| `LLM_ENDPOINT_RE` | prompt-cache hook | `api\.anthropic\.com/v1/messages` | Regex for the LLM endpoints the hook watches |

### The 15% copy variation check

`scripts/check-copy-variation.py` measures your FINAL emails, with custom fields filled in and spintax expanded, and blocks the push when any body line reaches more than 15% of recipients, any line is identical for everyone, or fewer than 90% of emails are distinct. It reads a JSON file of your templates and leads before you send, or a live Smartlead campaign after you load it. Full rules, the input format and a Claude/Codex prompt that does the same check by hand: produce-campaign section 7.1.

```bash
python3 scripts/check-copy-variation.py --rendered rendered.json --client ACME
bash scripts/tests/test-check-copy-variation.sh   # proves it fails on repeated copy
```

Greetings (including "Hola, Ana." and "Dear Ana,"), Spanish and English sign-offs, the inbox signature, a line that is only a `%sender-...%` token, and up to two short name lines after the sign-off are not counted as body copy. Use `--copy-field NAME` for a short custom field that carries copy rather than lead data, and `--exclusions` to supply greeting and sign-off patterns for another language.

---

## Credits

Built by [Jack Kelly](https://www.linkedin.com/in/jack-kelly-my-cold-leads/) at [MyColdLeads](https://mycoldleads.com).

Our copywriting methodology has been shaped by several practitioners whose work we admire and recommend:
- **Eric Nowoslawski** ([Growth EngineX](https://www.youtube.com/@GrowthEngineX)) - cold email copy, personalization strategy, and deliverability best practices
- **Josh Braun** - email structure and conversational tone
- **ColdIQ** ([coldiq.com](https://coldiq.com)) - signal-based targeting and sales signal classification

Follow me on LinkedIn for more tools and posts about our stack.

## Changelog

**November 2026** - Closed the gaps an outside code review found, and caught up with what we changed in production since September.
- *Push wrapper:* now checks suppression (contact and company domain), email status, prior replies, merge fields, a signed approval that hashes every lead and the template, that the campaign matches the client, and live platform membership so a lead already queued or recently sent elsewhere is not pushed again. Optional per-client rule to exclude personal mailboxes.
- *Hardening:* the proof is now per campaign and written by `scripts/verify-hardening.py` after a live read; one campaign's proof no longer unlocks another. The verifier also fails a campaign-level gap (the gap belongs on each inbox) and a follow-up percentage that differs from the agreed value.
- *Hooks:* read MCP tool calls as well as Bash and file writes, block when they cannot parse a call, and require a logged reason for any bypass marker.
- *Copy variation checker:* English sign-offs, "Hola, name" greetings, sender-token lines and the closing block are no longer scored as body copy; `--copy-field`; template-only mode; deleted A/B variants ignored.
- *Skill:* split from one 138 KB file into an 8 KB index plus phase files read on demand. New: offer / value-equation gate before any copy, cohort ledger, partner campaign type, DNS and link receipts before launch, follow-up percentage per sequence length. Fixed: post-push "fix and re-push" steps that contradicted the approval rule, the 98%-on-10-samples claim, the stale dedup note, the regex-versus-model contradiction (scripts count, models judge; no automatic word swaps).
- *Schema:* unique key on contacts so `ON CONFLICT` dedupes, `campaign_approvals`, and columns for greeting status and website identity.
- *README:* an honest list of what is enforced by code, what is instruction only, and what is described but not shipped.

**September 2026** - Section 7.1 is now the full copy variation check we run before every push: no body line in more than 15% of the final emails, zero fixed lines, 90% distinct, with the script (`scripts/check-copy-variation.py`) and its test. Replaced the old "~5 variation streams" and "3-5 spin points per sentence" guidance. Also brought the skill back in line with how we actually run campaigns: a real-email review with subject variants now gates every push, thin research drops a contact to a sourced floor opener instead of out of the cohort, bridges are achievement-framed and checked for repetition, and new gates cover stale emails, ICP over-exclusion, greeting names, invented initialisms, whose news a fact is, sequence structure and structure rotation. We also removed internal figures from the examples, made the schema match every query in the skill, and shipped a client config template and a push wrapper.

**August 2026** - Corrected six rules that production disproved: outreach is now logged at push time rather than after the send, one 90-day cooldown replaces the old 40/60-day split, cross-campaign dedup checks send history instead of campaign membership, contact discovery starts with free search before paid, model defaults dropped to the small model with mandatory prompt caching, and bypassing the platform block list is now explicitly forbidden. Added the abstention contract, source-quoted research, company-identity checks, deliverability hardening, durable writes, circuit breakers and a run retro. Fixed three tables the skill queried that the setup SQL never created.

**April 2026** - Initial release.

## License

MIT - use it, modify it, share it. If it helps you land your first client or improve your campaigns, that's all we wanted.
