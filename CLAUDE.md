# Campaign Production Rules

These rules govern how Claude Code operates when running the produce-campaign skill. They encode quality standards, prompt design patterns, and operational safeguards learned from running real campaigns.

## Step Excellence - Fix Before Proceeding (NON-NEGOTIABLE)

Every step in a multi-step pipeline MUST reach an acceptable pass rate BEFORE moving to the next step. Accepting poor results at one step and carrying them forward compounds failure across the pipeline.

### The Rule

When executing any multi-step process (campaign production, enrichment pipeline, contact discovery, variable generation):

1. Define the expected yield/pass rate for each step BEFORE starting
2. After completing each step, measure the actual result against the expectation
3. If the step falls significantly below expectation: STOP. Do not proceed.
4. Diagnose why the step failed - wrong API parameters? Wrong data source? Bad filters?
5. Fix the step and re-run until it reaches an acceptable pass rate
6. Only THEN move to the next step

### Typical expectations

| Step | Typical expectation |
|------|-------------------|
| Domain enrichment | 70-90% of companies get a domain |
| Company research | 80%+ return useful snippets |
| Contact discovery | 50%+ of companies yield a contact |
| Email waterfall | 40-50% find rate |
| Variable generation | 95%+ of contacts get valid variables |
| Copy quality (QA pass) | 98%+ pass rate |
| Name normalization | 100% Title Case, 0% raw domains |
| Campaign loading | 100% of qualified leads loaded |

### Anti-patterns

- "We got 6% on this step, let's work with the 6%" - NO. Fix the step.
- "Only 17% returned results, moving on" - NO. Try different sources, retry failures.
- Reporting a low yield as a final result without attempting to improve it
- Moving to variable generation with insufficient contacts to meet the campaign target

---

## Pipeline Rigor - Think in Steps, Exhaust All Tools (NON-NEGOTIABLE)

Every multi-step pipeline must be approached with logical step-by-step thinking. Map the funnel BEFORE executing. Enrich BEFORE acting. Exhaust ALL tools at each step. Track EVERYTHING.

### Before starting any pipeline:
1. Write the funnel - map every step with expected inputs, outputs, and yield rates
2. Enrich before you act - never skip enrichment. If you have 1,000 domains, learn about them FIRST. Filter out rubbish BEFORE spending credits on the next step.
3. Track every search method - persist which tool searched which record and what the result was. If Method A fails on a record, that record is a candidate for Method B.

### At each step:
4. Exhaust ALL available tools - when one tool has low yield, try every other tool before reporting the yield
5. Question every drop-off - if 1,000 inputs produce 190 outputs (19%), that's a red flag. Ask why.
6. Contacts without email are still contacts - if a tool finds a person but no email, that contact goes to waterfall

### After completing a pipeline:
7. Present the full funnel proactively - show every step with actual numbers. Don't wait to be asked.

---

## Prompt Design Rules

### Variables ALWAYS at the end (NON-NEGOTIABLE)

Keep the first 1,100+ characters of the prompt identical across requests (system instructions, ICP rules, static context). Put ALL dynamic variables in a `## VARIABLES:` section at the very END of the prompt.

This enables prompt caching on OpenAI, Anthropic, and any LLM provider that supports it. A 1,000-record run with variables scattered throughout costs 3-5x more than with variables at the end.

### Plain text only in email copy

No markdown (`**bold**`, `- bullets`). Smartlead sends plain text. Accented characters in Spanish (or your target language) are still required.

### Smartlead HTML formatting

When saving sequences via Smartlead API, use `<div>text</div>` for each line. For paragraph breaks use a bare `<br>` between divs - NOT `<div><br></div>`. When building HTML from arrays, ALWAYS `.join('')` NOT `.join('\n')`.

Pattern: `<div>First paragraph.</div><br><div>Second paragraph.</div>`

### Spintax rules

- **No body line in more than 15% of the final emails** once custom fields are filled and spintax is expanded, **zero fixed body lines**, and **at least 90% of emails distinct**. Run `scripts/check-copy-variation.py` before every push (produce-campaign section 7.1)
- **10-15 spintax groups per email** - above 15 body groups the copy reads machine-spun
- **Single word/phrase spintax ONLY** - sentence-level swaps are banned. Spin individual words: `{real|clara}`, `{captar|atraer}`
- **Every line moves** - the most repeated lines (opener, CTA) need ~8+ renderings to stay under 15%
- **Subject lines: 10+ quality-passing variants per persona**; vary signatures and unsubscribe wording across inboxes too
- **NEVER use time-dependent phrases** like "this week" in spintax - breaks on different days
- **NEVER put {{variables}} inside spintax braces** - `{Hello {{first_name}}|Hi {{first_name}}}` will BREAK Smartlead
- Spintax is a volume/deliverability tool, not a quality tool

### Smartlead custom fields are PLAIN DATA only

NEVER put spintax (`{A|B}`), system variables (`%signature%`, `%email%`), or any Smartlead-processed syntax inside custom field values. They will NOT resolve. Custom fields store pre-computed content. All Smartlead-processed elements go in the sequence template.

---

## Copy Quality Rules (NON-NEGOTIABLE)

### Grade 5 reading level / Bar conversation test

- Max 15 words per sentence. Aim for 10.
- One idea per bullet/sentence.
- Read every output out loud. Would you say this to someone over a beer? If it sounds like a brochure, rewrite it.
- Concrete over abstract: "your 12 hotels" not "your locations"

### Banned corporate jargon

Replace these with plain language (Spanish; adapt to your language):
- implementar -> poner en marcha
- optimizar -> mejorar
- integrar -> conectar
- supervisar -> controlar
- gestionar -> llevar
- configurar -> ajustar
- avanzado -> moderno
- innovador -> nuevo
- solución -> herramienta
- monitoreo -> seguimiento
- crucial/clave -> importante
- eficiencia -> rendimiento

### NEVER condescending (ZERO TOLERANCE)

Email copy must NEVER imply the lead is doing a bad job. Banned patterns: "you're missing things", "without realizing it", "you don't have control", "you're lacking", "you lose sight of". Frame challenges as natural operational realities that come with growth - not personal failures.

### Single data point rule

One fact. One. Pick the single most relevant finding. Ignore the rest. "60 years running AND three awards" = two facts = FAIL. Pick one.

### Observation rules

- Triggers: state only the trigger. "Saw you opened the Manchester depot." - stop there.
- NEVER include the company name in observation fields - the template already includes it
- If the company could have written the sentence themselves on their homepage, it's a tagline, not an observation
- No marketing language or editorial opinions ("America's most urgent project" - use the actual name)

### Relevancy beats personalization (CRITICAL distinction)

Personalization without relevancy is WORSE than no personalization at all. It wastes space, annoys the reader, and proves you didn't do real research - you just scraped a data point and stapled it to a pitch.

**BAD - personalized but irrelevant:**
"Hi John, I saw your company has been running for 32 years, so I thought you would appreciate an automated workflow."

What does 32 years in business have to do with workflow automation? Nothing. The lead reads this and thinks "this person doesn't understand my business."

**GOOD - personalized AND relevant:**
"Hi John, I saw your support team spends 1-2 hours/day responding to cases and thought you would appreciate an automated workflow."

The observation is directly connected to the offer. The lead reads this and thinks "they actually looked at what we do."

The rule: every observation must connect to your offer in a way the lead can see without you explaining it. If you have to add "so I thought you would appreciate..." to bridge an irrelevant fact to your product, the observation is wrong. Pick a different fact.

### Generic AI personalization is also POISON

Generic AI first-lines ("I saw your company helps people with X...") perform significantly WORSE than no personalization at all. What works:
- GOOD: Targeted product-focused AI that calculates YOUR value for THEM
- GOOD: Specific enriched data proving real research ("your 4.2-star rating", "your restaurant in Toledo")
- BAD: Describing THEIR company back to them ("As a leader in [industry]...")

### CTA rules

- ALL CTAs must be questions, never statements
- BEST: Value question ("If we could help with X, would that be useful?")
- GOOD: "Thoughts?" / "Does this sound familiar?"
- BANNED: Passive CTAs ("if you're interested...", "feel free to...", "when you have time...")
- The meeting often comes naturally from the reply - don't force it in the email

### PS Line rule

Every E1 email should include a PS line with a DIFFERENT value prop angle. If main body = "save time", PS = "save money". The PS must be a genuinely different benefit lens on the same product.

### Case studies / Social proof

- Do NOT name the case study company in email copy
- Just describing outcomes without naming correlates with top-performing campaigns
- DO: "A logistics company with 40 depots cut missed pickups by 30%"
- DON'T: "We helped Acme Corp cut missed pickups by 30%"

---

## Campaign Copy Quality Scoring

Score every campaign before launch using this framework:

**Composite: (0.40 x Copywriting) + (0.35 x Targeting) + (0.25 x Variables)**

| Score | Rating | Action |
|-------|--------|--------|
| 80-100 | Excellent | Proceed to launch |
| 65-79 | Above Average | Flag issues, proceed if approved |
| 50-64 | Average | Auto-rewrite and re-score |
| 35-49 | Below Average | Auto-rewrite and re-score |
| 0-34 | Poor | Full rewrite required |

### Anti-pattern deductions

- GENERIC_AI_COMPANY_OBSERVATION: -30 points (critical)
- SPAM_CRITICAL: -30 points
- FAKE_REPLY (Re:/Fwd: in subject): -15 points
- NO_PERSONALIZATION: -15 points
- MISSING_CTA: -15 points
- WEAK_CTA (passive): -7 points
- EMAIL_TOO_LONG (>150 words E1): -7 points
- NO_PS_LINE: -7 points
- NAMED_CASE_STUDY: -7 points

---

## Model Selection

**Default to the small model. Upgrading is a decision, not a reflex.**

**Pin the model per prompt** in your prompt library and use that one. For a new prompt, default to the cheapest capable small model (GPT-4o-mini class), and a Haiku-class model for tone-sensitive copy.

| Task | Default | When to reconsider |
|------|---------|-----------|
| Company name normalization | Cheapest small model (GPT-4o-mini class) | Never. This task does not need more. |
| Classification, extraction, ICP checks | Cheapest small model (GPT-4o-mini class) | Only if a well-iterated prompt still misses 98% |
| Observation generation | Pinned model, else cheapest small model | Only if a well-iterated prompt still misses 98% |
| Bridge sentences, other tone-sensitive copy | Pinned model, else Haiku-class | Only if a well-iterated prompt still misses 98% |
| Bullet generation | Pinned model, else cheapest small model | Only if a well-iterated prompt still misses 98% |
| Quality review / AI audit | Haiku-class or cheapest small model | Never |
| Pipeline design, config, debugging | Your best model | This is one-off reasoning, not a loop |

**Show a cost estimate before every paid run:** records, model, estimated dollars. Get agreement first. If the real cost heads past twice the estimate, stop and re-estimate.

Never put a large model in a bulk loop without deciding to. It is 10-30x the cost on a thousand-record run, and it is almost never the reason quality is bad - the prompt is. Iterate the prompt first.

Bad output is a prompt problem until proven otherwise. Before upgrading, state the cost difference for the actual batch size and get a human to agree to it.

### Prompt caching is not optional

Any loop of more than about five calls that shares a system prompt MUST be cached. This is what the variables-at-the-end rule above is *for* - it is not a style preference.

- Keep the first 1,100+ characters byte-identical across every call in the run
- Put per-record data at the very end, under `## VARIABLES:`
- Send the provider's cache directive (`cache_control` on Anthropic, automatic prefix caching on OpenAI)
- A single stray timestamp, record ID, or shuffled instruction near the top silently voids the cache for the whole run

Wrap your API caller in one function that always sets this, rather than trusting each script to remember. We burned a day's budget in an afternoon on an uncached loop that also overwrote its own output with error strings.

---

## Never Switch Off the Block List (NON-NEGOTIABLE)

Every sending platform has flags that bypass its own suppression lists. On Smartlead they are `ignore_global_block_list` and `ignore_unsubscribe_list`. **Both must be `false` on every push, from every code path, forever.** There is no legitimate use case.

You will be tempted the first time a push gets partially rejected. It does not even work: the platform runs its own enforcement pass afterwards and strips those leads out anyway - after some of them have been emailed. We pushed a few hundred leads this way; the platform accepted them, then stripped about two thirds within 24 hours.

The block list is how bounce history and unsubscribe requests are enforced. If you think you need to bypass it, the real fix is upstream: get the address removed from the block list properly, or mark it do-not-contact on your side and stop pushing it.

Related: set `ignore_duplicate_leads_in_other_campaign` to `false` too, but for the opposite reason - see the cross-campaign dedup gate in the skill. That platform-side check is blind to whether anything was ever sent, and over-blocks. Your own sent-history gate is the authority.

---

## Persist Paid Work the Moment It Exists (NON-NEGOTIABLE)

Anything that costs money to produce - an AI generation, a scrape, an enrichment, a vendor lookup - gets written to its destination as soon as it exists. Never accumulated in memory and flushed at the end.

- **Write per record**, not per batch and not at the end of the phase
- **Wrap every row** so one bad row costs one row, never the rest of the run
- **Report `attempted / succeeded / failed`** with the failing identifiers, not a single number
- **Read the error body.** A bare "409: Conflict" with the response discarded is undiagnosable an hour later

A three-hour run held thousands of finished results in memory, wrote at the very end, and lost about 40% of them to one rejected request. All of it had been paid for.

This applies to every bulk loop in the pipeline: research, variable generation, the email waterfall, the push itself.

---

## Two Crashes Means Stop (NON-NEGOTIABLE for anything unattended)

Once a phase graduates onto scheduled infrastructure, one crash can be transient. **A second consecutive crash means kill everything.** No third retry.

- Count consecutive failures in storage that survives a restart - a database row or a KV flag, never a variable in the process
- Check the counter before the risky operation, and exit cleanly if it is tripped
- Set the platform's restart policy to never, or at most one retry. The common default is ten.
- Clearing the breaker requires a human

Auth failures, rate limits and spend all compound on retry: each restart makes it worse. Ours retried a third-party login five times in ninety seconds and got the account session invalidated. A less forgiving service would have locked the account or drained the budget.

---

## AI Cost Reporting (NON-NEGOTIABLE)

After EVERY production run that calls external AI APIs, immediately report:
- Number of API calls per model
- Estimated token usage
- Estimated cost in USD

Do this before moving to the next step.

---

## Quality Review = AI Subagent, NEVER Regex Scripts

When reviewing generated content for quality issues, ALWAYS use a Haiku subagent - NEVER a regex/pattern-matching script. A script only catches what you hardcode; Haiku reasons about context, tone, marketing language, factual accuracy, and catches orders of magnitude more issues.

---

## Subject Lines and Company Names - Casing Rules

- **Static text in subject lines**: always lowercase
- **Company/brand names in subject lines**: Title Case (proper nouns)
- **Company name normalizations**: ALWAYS Title Case
- **Pre-launch check**: verify no ALL CAPS values in any field that appears in subject lines

### The directory test (run before locking any subject line)

Ask: could this be mistaken for an automated notification from a review site, a listings service, or an aggregator? If yes, rewrite it. The subject has to feel like a person, not a service.

A city name on its own always fails this test. "a quick question from Madrid" reads like an automated digest, and gets skipped. Use something true of that one business instead: a recent event, a count, the business's own name, the topic you are actually writing about.

Decision order:
1. If you have a specific fact about **this** company, use it
2. Otherwise use a theme that hints at the relevant topic without naming a city
3. Never ship a city-only subject

---

## Per-Company Recipient Cap - Scoped, Not Blanket

Emailing several decision makers at one company is normal and often desirable. Do not cap it by default.

Cap only when the receiving server is shared at scale: large enterprises and multinationals, or any push that would land more than roughly five to ten addresses at one email domain in the same sending window. More than a dozen contacts at one multinational tripped that company's inbound throttling for us.

Person-level dedup always applies: the same individual never appears twice.

This is an email constraint specifically. It comes from the receiving mail server, so it does not transfer to other channels.

---

## Smartlead Sequence API Gotchas

1. `.join('\n')` causes double spacing - ALWAYS `.join('')` for HTML arrays
2. Spintax doesn't resolve in custom fields - pre-resolve before pushing
3. `<div>{{body_var}}</div>` adds extra wrapping - if the custom field already contains `<div>` tags, the template should be just `{{body_var}}`
4. Max 200 custom fields per lead - Smartlead hard limit
5. Empty custom fields render as blank, causing double spaces
6. `seq_variants` NOT `sequence_variants` for POST - they use DIFFERENT field names for read vs write
7. ALWAYS include `id` for existing sequences - missing `id` = Smartlead creates NEW records, orphaning analytics permanently
8. Wrap delay: `seq_delay_details: { delay_in_days: N }` - NOT flat `delay_in_days`
9. Body wrapper: `{ "sequences": [...] }` - bare array = 400 error
