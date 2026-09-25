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

This is an **email** pipeline. Everything here - the sequence structure, the copy length, the per-company recipient cap, the cooldowns - assumes email and a receiving mail server.

If you add another channel later, the parts that do not transfer are: the per-company cap (a mail-server constraint, not a rule of outreach), message length norms, and the dedup rules, since a person can legitimately be in an email cohort and a social cohort at different times. Decide the channel up front rather than bolting it on, because almost every phase branches on it.

### Spam checking

The pipeline includes a spam check phase before every push. Instead of building your own spam word database, you can use our free [MCL Spam Word Checker](https://mycoldleads.com/spam-checker) - a real-time updated database of spam trigger words sourced from multiple providers. The skill references this tool at the spam check step.

## How to install

1. Clone this repo (or just download the files)
2. Copy the whole `.claude/` directory into your project root: the commands, the hooks and their tests. If you already have a `.claude/` directory, merge it in rather than replacing it.
3. Copy `scripts/`, `prompts/` and `setup/` into your project root
4. Copy `CLAUDE.md` to your project root (or merge with your existing CLAUDE.md)
5. Turn the hooks on: merge the entries from `.claude/settings.example.json` into your `.claude/settings.json` (see "The gates are enforced" below), then run `bash .claude/hooks/tests/run-tests.sh`
6. Run the SQL in `setup/schema.sql` in your Supabase SQL editor to create the required tables. It is safe to re-run, and it upgrades an older install.
7. Copy `setup/campaign-config.template.md` once per client and fill it in
8. Open Claude Code and type `/produce-campaign YourCompanyName`

That's it. Claude will guide you through every phase.

## How it works

The pipeline has 14 phases. Each phase has a gate - you can't skip ahead without completing it.

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

## The gates are enforced, not just documented

The skill describes 14 phases with a control at each one. Markdown is advice - an
agent can read a rule and skip it anyway, and the skipping is invisible until the
emails are already sent. So the rules that cost real money are also wired as
PreToolUse hooks, which refuse the tool call outright.

Copy the entries from `.claude/settings.example.json` into your own
`.claude/settings.json` to turn them on. If you already have a settings.json, add
the entries inside the arrays rather than replacing the file.

| Hook | Refuses | Bypass marker |
|---|---|---|
| `pretooluse-push-safe-required.sh` | Switching off the platform's suppression list (never bypassable), and raw lead pushes that skip the dedup/cooldown wrapper (`scripts/push-safe.py`). It is a guard, not a sandbox: any script named `push-safe.*` is trusted | `PUSH_SAFE_OK:` |
| `pretooluse-deliverability-hardening.sh` | Sending, activating or running `push-safe.py --apply` without a fresh hardening proof. After a live read shows open and click tracking off and plain text on, record it with `touch .claude/campaign-state/hardening-<campaign_id>.ok`. The proof expires after `HARDENING_MAX_AGE_MIN` minutes (default 120) | `HARDENING_OK:` |
| `pretooluse-custom-field-syntax.sh` | Spintax, signature tokens, or a variable nested inside spintax, in a custom field value | `CUSTOM_FIELD_OK:` |
| `pretooluse-abstention-guard.sh` | The `NOT_FOUND` abstention token reaching a payload bound for a lead | `ABSTENTION_OK:` |
| `pretooluse-prompt-cache-guard.sh` | A loop of LLM calls with no `cache_control` on the system block. Anthropic-specific: OpenAI caches long prompt prefixes automatically, so by default it only watches the Anthropic endpoint (`LLM_ENDPOINT_RE`) | `CACHE_OK:` |
| `pretooluse-durable-writes.sh` | A loop that spends money per record and writes only at the end | `DURABLE_WRITES_OK:` |

Every bypass is written to a log next to the hooks. Using one for a production run
is a bug in the caller, not a workaround.

### Prove they work before you trust them

```bash
bash .claude/hooks/tests/run-tests.sh
```

30 cases: each gate is fed a known-bad input it must refuse and a known-good input
it must allow. A gate that has never gone red might be working, or might be
silently doing nothing - this is how you tell. Two real bugs in these hooks were
caught by that harness before release, including one where a non-greedy regex
stopped at the spintax's own closing brace so the very thing the gate existed to
catch fell outside what it inspected.

They are plain bash and Python with no dependencies. Read them; they are short.

### The push wrapper

`scripts/push-safe.py` is the one sanctioned way to load leads into Smartlead. It is a dry run unless you pass `--apply`. It skips invalid emails, repeats of the same person and anyone inside the 90-day cooldown, forces the suppression settings to false, posts in batches of up to 1,000, reconciles against `total_leads`, writes the outreach log at push time and reports `attempted / succeeded / failed / skipped` with reasons. It reads the cooldown from your `outreach_log` table (`DATABASE_URL`, needs `psycopg`) or from a JSON export (`--outreach-log`).

```bash
python3 scripts/push-safe.py --campaign 1234567 --client ACME --leads leads.csv --outreach-log outreach_log.json
python3 scripts/tests/test-push-safe.py   # proves cooldown, dedupe and forced settings, no network
```

### Environment variables

| Variable | Used by | Default | What it does |
|---|---|---|---|
| `SMARTLEAD_API_KEY` | `scripts/push-safe.py --apply`, `scripts/check-copy-variation.py --campaign` | none | Your Smartlead API key |
| `DATABASE_URL` | `scripts/push-safe.py` | none | Postgres connection string for the `outreach_log` table (cooldown read, push-time write). Use `--outreach-log FILE.json` instead if you have no direct database access |
| `PUSH_SAFE_WRAPPER` | push-safe hook | `push-safe` | Base name of your push wrapper, if you renamed it or wrote your own |
| `HARDENING_MAX_AGE_MIN` | deliverability hardening hook | `120` | Minutes a hardening proof file stays valid |
| `ABSTENTION_TOKEN` | abstention hook | `NOT_FOUND` | The token your prompts return when the source does not support an answer |
| `LLM_ENDPOINT_RE` | prompt-cache hook | `api\.anthropic\.com/v1/messages` | Regex for the LLM endpoints the hook watches |

### The 15% copy variation check

`scripts/check-copy-variation.py` measures your FINAL emails, with custom fields filled in and spintax expanded, and blocks the push when any body line reaches more than 15% of recipients, any line is identical for everyone, or fewer than 90% of emails are distinct. It reads a JSON file of your templates and leads before you send, or a live Smartlead campaign after you load it. Full rules, the input format and a Claude/Codex prompt that does the same check by hand: produce-campaign section 7.1.

```bash
python3 scripts/check-copy-variation.py --rendered rendered.json --client ACME
bash scripts/tests/test-check-copy-variation.sh   # proves it fails on repeated copy
```

---

## Credits

Built by [Jack Kelly](https://www.linkedin.com/in/jack-kelly-my-cold-leads/) at [MyColdLeads](https://mycoldleads.com).

Our copywriting methodology has been shaped by several practitioners whose work we admire and recommend:
- **Eric Nowoslawski** ([Growth EngineX](https://www.youtube.com/@GrowthEngineX)) - cold email copy, personalization strategy, and deliverability best practices
- **Josh Braun** - email structure and conversational tone
- **ColdIQ** ([coldiq.com](https://coldiq.com)) - signal-based targeting and sales signal classification

Follow me on LinkedIn for more tools and posts about our stack.

## Changelog

**September 2026** - Section 7.1 is now the full copy variation check we run before every push: no body line in more than 15% of the final emails, zero fixed lines, 90% distinct, with the script (`scripts/check-copy-variation.py`) and its test. Replaced the old "~5 variation streams" and "3-5 spin points per sentence" guidance. Also brought the skill back in line with how we actually run campaigns: a real-email review with subject variants now gates every push, thin research drops a contact to a sourced floor opener instead of out of the cohort, bridges are achievement-framed and checked for repetition, and new gates cover stale emails, ICP over-exclusion, greeting names, invented initialisms, whose news a fact is, sequence structure and structure rotation. We also removed internal figures from the examples, made the schema match every query in the skill, and shipped a client config template and a push wrapper.

**August 2026** - Corrected six rules that production disproved: outreach is now logged at push time rather than after the send, one 90-day cooldown replaces the old 40/60-day split, cross-campaign dedup checks send history instead of campaign membership, contact discovery starts with free search before paid, model defaults dropped to the small model with mandatory prompt caching, and bypassing the platform block list is now explicitly forbidden. Added the abstention contract, source-quoted research, company-identity checks, deliverability hardening, durable writes, circuit breakers and a run retro. Fixed three tables the skill queried that the setup SQL never created.

**April 2026** - Initial release.

## License

MIT - use it, modify it, share it. If it helps you land your first client or improve your campaigns, that's all we wanted.
