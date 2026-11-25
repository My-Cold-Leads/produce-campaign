<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

## Phase 6: Variable Generation

### 6.0 - Offer Gate: the value equation (HARD GATE before any copy)

No copy, no prompt and no variable is written until the offer has been scored and the user has approved it. No amount of copy iteration rescues a weak offer, and a bare "would you be open to a quick call" is not an offer.

Score the offer with the value equation (Alex Hormozi, *$100M Offers*): value goes up with the **dream outcome** and the **perceived likelihood of getting it**, and down with the **time delay** and the **effort and sacrifice** asked of the buyer. Write one plain sentence for each, for this persona:

1. **Dream outcome** - what does this person get, as a noun? An audit of something they own, a benchmark against peers, a teardown, a calculator, a sample of the work.
2. **Why they would believe it** - the proof you can actually show (a named or anonymised result, a number with a source). No proof means say so; do not invent one.
3. **Time to value** - how soon after replying do they hold the thing?
4. **Effort asked** - what must they do? The first ask sits at the bottom of the friction ladder: a reply or a click. A call as the first ask needs a written reason from the user.

Save the four answers, the first ask and the user's approval (their words, the date) as an offer scorecard in the client config (section 15 of `setup/campaign-config.template.md`). Then:

- The CTA in every email must be the scorecard's first ask. If the rendered CTA asks for a call and the scorecard says reply, the copy is wrong, not the scorecard.
- If any of the four answers is empty or generic ("save time", "grow revenue"), stop and fix the offer with the user first.
- If the client already has an approved scorecard for this persona and nothing changed, reuse it and say so.

This gate is an instruction, not code. Treat a missing scorecard as a hard stop anyway.

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

**The production target is at most 2% failures. You cannot measure 2% on 10-20 samples, so the bar on a small sample is zero failures, and the 2% is measured later on the full-batch QA sample (6.3b). "Looks good on 10" is the start of the ladder, not the end.**

1. Pick 10-20 test companies (diverse sectors, at least 2 per major sector)
2. Generate all variables for those companies using the prompt
3. Output in Standard Format (see below)
4. Review against the quality rules in 6.4 below - apply them yourself before showing the user
5. Show the output to the user only when the offer or the prompt is new or changed (touchpoint 2: the offer and 10 real examples). Otherwise do not stop: apply the checks yourself and carry on.
6. Apply changes (the user's feedback at touchpoint 2, or your own check results), regenerate the same 10-20 and compare
7. Count failures against the 6.4 rules. On 10-20 samples any failure means: fix the prompt and regenerate. Do not proceed.
8. When a fresh set of 10-20 comes back with zero failures, climb the sample ladder in `/iterative-prompting` (10, 20, 50, 300) using its pass bar at each rung. Save the prompt to your library, THEN run full production

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

**This loop runs every time - including re-runs of existing prompts. Even if the prompt hasn't changed, re-run the small-sample check (zero failures on 10-20 fresh records) on the current data.**

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

**Division of labour, used everywhere in this document:** a script DETECTS and COUNTS anything with an exact definition (a banned word is present, a line's share, length, punctuation, an empty field). A model JUDGES meaning (tone, plausibility, fit inside the sentence). A script never rewrites meaning, and a model is never trusted to count.

After generation and BEFORE validation:

1. **Scan every generated field for banned words with a word-boundary pattern** (`\b...\b`, so "autoclaves" does not match "clave"). Starter list for Spanish, adapt to your language: `clave`, `sistema`, `eficiencia`, `optimizar`, `implementar`, `integrar`, `supervisar`, `gestionar`, `configurar`, `avanzado`, `innovador`, `solución`, `monitoreo`, `crucial`, `preciso`.
2. **Do not swap the word automatically.** A blind swap ignores gender and number agreement and can change a sourced fact ("sistema" is not always "equipo"). Send the record back for regeneration with the offending word named in the retry. After two failed retries the record falls a tier (6.4) or is held for a manual rewrite.
3. **Mechanical fixes may be deterministic:** trailing punctuation that the template already supplies (read the E1/E2 templates first; this is per campaign), double spaces, a leaked field prefix.
4. **Then run validation** on the post-processed text.

**Why:** models keep producing banned words for some industries however the prompt is worded. The scan is cheap insurance; the rewrite stays with something that can read the sentence.

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

### 6.4c - Edge Case Cleanup Pass (MANDATORY, before the real-email review in 7.7)

Every bulk run of 500+ records leaves 1-5% with subtle issues that passed the prompt and the validator: a hedge word mid-sentence, an awkward phrase, near-duplicate openers. That is expected. Clean them here, in your database, **before** the approver sees anything. Nothing is on the sending platform yet, so there is nothing to patch there.

1. **Scan ALL generated records** (not a sample) for known edge-case patterns:
   - Hedge words anywhere in the sentence (Spanish, adapt to your language): `imagino`, `supongo`, `seguro que`, `probablemente`, `creo que`, `me imagino`
   - Colloquial spam openers that leaked: `Mira,`, `Oye,`, `Pues,`, `Vaya,`
   - Banned words from the client-specific rules
   - Near-duplicate openers (any of the top 5 starters above 10% of the batch)
2. **Fix each flagged record**: regenerate it, or edit it by hand. A deterministic edit is fine only when it deletes a hedge clause without touching the fact (`, imagino que X` -> `, X`); re-read each result.
3. **Save the fixes to `campaign_variables`**, re-render the changed emails and re-run the validator on them.
4. **Add the new patterns to the prompt's banned list** now, so the next run catches them at generation time.
5. **Tell the user:** "Edge cases cleaned: N records. Pattern X added to v{N+1} of the prompt."

Do not start another full prompt iteration to chase the last 2%. Fix, record the pattern, move on.

**After the approval in 7.7 this pass is closed.** Any later change to a lead or the template is a new approval, and the wrapper enforces that.

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

The rules are in `CLAUDE.md`, "Model Selection" and "Prompt caching is not optional", and apply here unchanged: small model by default, model pinned per prompt in the prompt library, a cost estimate the user agrees to before every paid run, stop and re-estimate at twice the estimate, prompt caching in any loop over about five calls, one shared calling function.

### 6.6 - AI Cost Reporting (NON-NEGOTIABLE)

After every production run that calls a paid AI API, report calls per model, estimated tokens and estimated cost in USD before the next step (`CLAUDE.md`, "AI Cost Reporting").

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
