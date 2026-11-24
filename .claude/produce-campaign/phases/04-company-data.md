<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

## Phase 4: Company Data Prep

### 4.1 - Company Name Normalization (HARD GATE - do not proceed without this)

**Skipping this causes raw domains like "acmelogistics.com" to appear in subject lines.**

**Step 1: Check what already exists**
```sql
SELECT
  COUNT(*) as total,
  COUNT(comp.normalized_name) as has_norm
FROM companies comp
WHERE comp.client_name = '{CLIENT}';
```

**Step 2: GPT-4o-mini for remaining gaps only**
- **Reuse first.** If a company already has a stored normalized name, use it. Generate only for rows where it is empty (see 1.5b).
- **MANDATORY: Check your prompt library for an approved normalization prompt first.** Only write a new one if none exists.
- Test on 20 diverse examples with zero failures, save to your prompt library, then follow the sample ladder in 6.3 before the full batch.
- Batch 50 at a time. Cost: ~$0.02/1,000 companies.
- **This step MUST run before pushing leads.** If the `company_name` field on your leads still matches the raw name in your database, normalization was skipped - go back and run it.

**Normalization rules:**
- **Strip legal suffixes and place qualifiers:** S.L., S.L.U., S.A., S.A.S., Ltd, Plc, GmbH, Inc, LLC, and trailing country or region tags like "(Chile)" or "Europe". "Acme Industries S.L." becomes "Acme Industries".
- **Title Case**, with connectors lowercase (de, del, y, la, of, and) and Spanish accents restored.
- **Never invent an initialism.** A short form is allowed only when those exact letters already appear as a token in the source name. "Contenedores Ejemplo del Sur S.A." becomes "Contenedores Ejemplo del Sur", never "CES". "ACME Iberia S.L." may become "ACME", because the token is in the source. Being a real, well-known acronym is not the test - the test has to be mechanical, because "is this a real brand acronym" is the judgement a model gets wrong at scale.

**Why:** the normalized name lands in subject lines. An initialism the company never uses reads as a label for somebody else.

**How to check:** for every output made only of capital letters, confirm that exact token appears in the source name. Any row that fails is an invented initialism - fix it before push.

**Step 3: Verify - zero tolerance for domain-as-name**
```sql
SELECT comp.domain, comp.normalized_name
FROM companies comp
WHERE comp.client_name = '{CLIENT}'
  AND comp.normalized_name IS NOT NULL
  AND comp.normalized_name ~ '\.[a-z]{2,4}$'
  AND comp.normalized_name NOT LIKE '% %';
-- Must return 0 rows
```

**ALWAYS use this fallback chain in generation queries:**
```sql
COALESCE(comp.normalized_name, INITCAP(LOWER(comp.company_name)), comp.domain) as normalized_name
```

### 4.2 - Company Research (SEPARATE AGENT - NON-NEGOTIABLE)

**Research and generation are ALWAYS separate steps. NEVER use one AI call to both research AND generate variables. If research fails, re-run research only. If generation fails, re-run generation only with cached research.**

**Step 1: Check your prompt library for research queries.** Use approved search query templates. Do not write new ones without checking.

**Step 2: Choose research method**

| Method | When to use | Cost |
|--------|------------|------|
| Serper (preferred) | Default. 3 queries/domain: triggers, growth, operations | ~$0.003/domain |
| Agent reads the site directly | When you need to understand the company, not just collect snippets | ~$0.005/domain |
| Hybrid | Serper for signals, direct read for context | ~$0.006/domain |

**Let the agent doing the reasoning do its own fetching (NON-NEGOTIABLE).**

Do not pre-fetch pages with a script, convert them to text, and hand the text to a model. That pipeline strips exactly the signals a reasoning model needs: that this is a cookie wall rather than a homepage, that this is the German parent rather than the Spanish subsidiary, that this domain is parked, that the page is in the wrong language for your campaign.

Give the agent a fetch tool and a fallback ladder, and let it decide when a fetch failed:

```
native fetch -> a text-extraction proxy -> a headless browser -> flag as scrape-failed
```

A scrape-failed company is not a company you guess about. It goes to the floor template.

**Source-gating (NON-NEGOTIABLE).** Every fact that reaches a generated field must carry:
- `source_url` - the page it came from
- `source_quote` - the sentence on that page that proves it

Verify the quote with a substring check against the fetched text. A model can invent a quote as easily as it can invent a fact, so an unverified quote buys you nothing.

**If a fact is not quotable from the source, it does not go in the email.** Never infer from the industry code, the sector, the company name, or what companies like this usually do. Downgrade to the safer template instead.

**The incident behind this:** a pre-fetch-then-summarise pipeline produced wrong observations for roughly 15% of one month's cohort, because the summarising prompt was working from thin text and filled the gaps by inferring from the industry classification. Recipients replied to say we had described equipment they did not have.

**Step 3: Structured signal extraction**

For each company, extract:
- `employees` (int)
- `signals` (array) - the same values as `signal_type` in 6.8, for example: expansion, hiring, leadership_change, merger_acquisition, partnership, product_launch, award, regulatory
- `locations` (array)
- `raw` (object) - full text per query type

**CRITICAL - Operations field generation (NON-NEGOTIABLE):**

When writing the `operations` field for a company, ALWAYS include the company's known address and industry classification as ground-truth anchors in the prompt:

```
Company: {company_name}
Known address: {address} {city}
Industry: {industry_description}

Based on the search results below, describe this company's operations in 2-3 sentences.
ONLY include information consistent with the known address and industry above.
If any search result describes a different city or a different industry, IGNORE IT - it is about a different company.
```

After generating `operations`, run this validation before saving:
1. Extract any city/location mentioned in the generated text
2. Cross-check against the company's known address in your database
3. If the generated text mentions a city that contradicts the known address: DISCARD and regenerate with stricter prompt
4. If the industry doesn't match the operations described: DISCARD - wrong company data in search results

**Why this matters:** In production, a manufacturer had operations generated from a different company's search results. The lead replied to say the description was wrong. Address anchoring would have caught this immediately.

**Step 4: Save cache**

Save to a local cache file keyed by domain. Checkpoint every 50 companies.

**Report AI cost after research completes.**

### 4.3 - Persist Research to Database (NON-NEGOTIABLE)

**Research data is expensive (SERP calls, API lookups, GPT analysis). It MUST be saved to your database immediately - not just to local files. Local files die with context resets. Your database survives forever.**

After research completes for each batch, write results back to your companies table:

```sql
UPDATE companies
SET
  personalization_data = $signals_json::jsonb,
  updated_at = NOW()
WHERE domain = $domain AND client_name = '{CLIENT}'
  AND (personalization_data IS NULL OR personalization_data = '{}'::jsonb);
```

**Structure for personalization_data:**
```json
{
  "employees": 150,
  "signals": ["expansion", "partnership"],
  "locations": ["Madrid", "Barcelona"],
  "raw": { "serper_triggers": "...", "serper_growth": "..." },
  "researched_at": "2026-03-22",
  "research_model": "gpt-4o-mini"
}
```

**Write each company's result the moment it exists, not at the end of the batch.**

This is the single most expensive lesson in this document. A three-hour research run held thousands of finished results in memory, wrote them at the end in one transaction, and lost about 40% of them to a single rejected request. Every one had been paid for.

The pattern:

```python
for company in companies:
    result = research(company)          # costs money
    try:
        persist(result)                 # write it NOW, one row
        succeeded.append(company.domain)
    except Exception as e:
        failed.append((company.domain, str(e)[:500]))   # keep the BODY, not just the code
        continue                        # one bad row costs one row
```

Three rules, all non-negotiable:

1. **Persist per record.** Not per batch, not at the end of the phase. If the process dies at minute 170 of 180, you keep 170 minutes of work.
2. **Wrap every row.** An unguarded loop turns one bad row into a lost run.
3. **Report `attempted / succeeded / failed`** with the failing identifiers, never a single number. And read the error body: "409: Conflict" with the response discarded is undiagnosable an hour later.

A local cache file is a convenience, not persistence. It gets cleaned, it does not survive a new machine, and nobody else can query it.

**This step runs IMMEDIATELY after research, BEFORE moving to Phase 5.** This phase MUST complete and save before Phase 5 begins. No exceptions.

### 4.4 - ICP Check Guardrails (HARD GATE after research)

If you run an AI classifier to confirm each company fits the ICP, treat it as a **default-accept negative filter**. Every company already passed your industry filter, so exclude only companies the page proves are a non-fit.

**Classes:**
- `ICP_FIT` - fits
- `SUBSIDIARY_OF_FIT` - a local operating subsidiary of a larger group, where the local company fits even if the website is the parent's. Without this class, subsidiaries get dropped whenever their domain resolves to a parent that does not operate in your country.
- `ICP_MISS` - a proven non-fit
- `ICP_UNCLEAR` - almost never; kept, not dropped

**Writing "default-accept" in the prompt does not produce default-accept.** A small model reads a homepage that does not mention a factory and writes "no evidence", which is exactly the inference you forbade. Enforce the posture in code:

1. **A MISS needs a reason from a fixed list** (for example: law/tax/accounting, bank/insurance, software/IT services, media, government, education, pure retailer, pure distributor, consultancy, hospitality, healthcare provider, holding company, NGO). No free text.
2. **Reasons that argue from absence** ("pure retailer, no production", "holding, no plant") **also need a quote from the page**, checked by substring against the fetched text.
3. **Dead, parked, 404, "coming soon", bot-wall and JS-only pages never reach the model.** They are kept as FIT by a code rule. An empty page is not evidence.
4. **Ask the model whose website this is.** If the page belongs to someone else, nothing on it can disqualify this company.
5. **Let the registry win over a brochure.** If the company's own name or industry code says it makes things, an absence-based MISS is overruled.

**How to check (every run):** read at least 40 random MISS rows with name and industry and judge them yourself - a drop you cannot defend in one sentence is a wrong drop. **A MISS rate above ~8% is a defect until proven otherwise.** Audit before the cohort moves on, and grade against the company name and registry data, not against the classifier's own reason field.

---

## Phase 4.5: Confirm the Website Belongs to the Company (HARD GATE)

**Run after research and contact discovery, before normalization and any generation.**

A wrong domain attached to a company record poisons two things at once, which is why it deserves its own gate:

1. **The personalization** - you write about a business your recipient does not run
2. **The contact list** - the people you then discover work at that other company, so you are emailing strangers about a stranger's business

Searching a company name and taking the first plausible domain produces this constantly. "Acme Aceros" resolving to a large construction group's domain means every contact you find is that group's staff.

**Validate the domain before contact discovery, not after.** Check the resolved domain against the company's identity first, so discovery never starts from a wrong site. When that check is weak, discover by company name and cross-check.

**Re-run this gate whenever the domain or the contacts change.** A verdict is only valid for the domain and contact list it judged. A re-resolved domain, a salvage re-enrichment, or a new discovery wave makes it stale. A rescued false exclude is re-judged with the corrected input, never pushed quietly past its old verdict.

**For each company, judge two things independently:**

| Axis | Question |
|------|----------|
| **Site identity** | Does the scraped homepage belong to this company, a parent or subsidiary, or an unrelated business? |
| **Contact identity** | Do the discovered contacts work at this company, or at whatever the domain actually belongs to? |

**Four verdicts:**

| Verdict | Meaning | Action |
|---------|---------|--------|
| `keep` | Both check out | Proceed normally |
| `floor_personalization` | Contacts are right, site is wrong or is a group page | **Keep the lead.** Strip every homepage-derived specific and use the floor template. |
| `review` | Ambiguous | Human look before it ships |
| `do_not_write` | Contacts belong to a different company | Exclude from this push |

**Open the TAM, do not over-drop.** `do_not_write` and `review` are not terminal - apply Phase 2.8 salvage here. A contact domain that genuinely derives from the target name, or a real parent-subsidiary relationship you had not recorded, is a false exclude and should be rescued. Bias the gate so false sends are near zero and false excludes are tolerable, because false excludes are recoverable and a wrong email is not.

Store the verdict per company and have both the renderer and the pre-push gate honour it, failing closed. A verdict nothing reads is a comment.

**Freemail policy depends on your TAM.** At large companies a decision maker on a Gmail address is anomalous and should go to `review`. At small businesses it is completely normal and should be `keep`. Set this per client rather than globally.
