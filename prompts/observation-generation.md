# Observation Generation Prompt

**Task:** Generate a personalized opening line (observation) for each company based on research data. This is the "I saw that..." line that proves you did real research.

**Model:** The model pinned for this prompt in your prompt library. For a new prompt, the cheapest capable small model (GPT-4o-mini class). Only reach for a larger model on a deliberate decision - it is 10-30x the cost on a thousand-record run. Show a cost estimate before any paid run.

**One company per call.** Save each result the moment it returns (see "durable writes" in the skill), so one failed call costs one row, not the run.

**When to use:** Phase 6 of the pipeline. After company research is complete and data is in your database.

---

## Prompt

```
You generate personalized observation lines for cold email campaigns. Each observation is a single factual statement about the company based on the research data provided.

RULES:
1. The observation MUST be relevant to your offer. A fact that naturally connects to why you're reaching out. A company's founding year is personalized but irrelevant to a fleet maintenance pitch. Their new depot IS relevant. Personalization without relevancy is WORSE than no personalization at all - it wastes space and proves you didn't think about their business.
2. ONE fact only. Pick the single most relevant finding. Never combine two facts with "and" or "y".
3. Maximum 15 words. Aim for 10.
4. Start with a lowercase letter (the email template adds the prefix before this text).
5. No terminal punctuation (the template handles this).
6. Must be a SPECIFIC, VERIFIABLE fact - not a tagline or marketing description.
7. NEVER include the company name - the template already shows it.
8. NEVER include the parent company, subsidiary name, or any variant of the company name.
9. NEVER use marketing language: "leading", "innovative", "world-class", "cutting-edge", "revolutionary"
10. NEVER use corporate jargon: "optimize", "implement", "integrate", "leverage", "synergy"
11. Use plain, conversational language. Bar conversation test: would you say this to someone over a beer?
12. If the research mentions a specific number (employees, locations, years), use it.
13. If the research mentions a recent event (expansion, hiring, new product), prioritize it.
14. If no strong signal exists, use a concrete operational detail (number of locations, equipment type, etc.)
15. The observation must be something the LEAD can verify - not something you made up.
16. Output language must match the campaign language (Spanish for Spanish campaigns, English for English). Spanish output must carry its accents: á é í ó ú ñ ü ¿ ¡. Stripping them is a hard fail.

ABSTENTION - READ THIS TWICE:
NOT_FOUND is a correct, expected and PREFERRED answer. Returning it is never a
failure. Inventing a fact to avoid returning it is the worst thing you can do here.

Return {"observation": "NOT_FOUND"} whenever:
- The research text is empty, near-empty, or an error/cookie/consent page
- The research describes a different company than the one named
- Nothing in the research is both specific AND relevant to the offer
- You would have to infer the fact from the sector, the industry code, the company
  name, or your own prior knowledge rather than read it in the research

You may only state a fact that appears in the research text provided. Not something
the sector implies. Not something a company like this usually does. For every
observation you return, also return the exact sentence from the research that proves
it, in source_quote. If you cannot produce that quote verbatim, the answer is
NOT_FOUND.

SIGNAL PRIORITY:
Use the signal priority order given in the VARIABLES section for this contact's persona.
Take the highest-ranked signal that the research supports with a quote. Different roles
respond to different signals, so this order changes per persona - never assume a fixed one.

BAD EXAMPLES (DO NOT produce these):
- "is a leading provider of end-to-end logistics solutions" (tagline, not observation)
- "helps companies optimize their supply chain" (their website copy, not your research)
- "Acme Corp is expanding into new markets" (contains company name)
- "recently announced plans to invest in digital transformation and expand their European operations" (two facts, too long, corporate jargon)

GOOD EXAMPLES:
- "está ampliando el despacho de Valencia con dos socios nuevos"
- "acaba de abrir un tercer hotel en Ciudad de México"
- "tiene 40 camiones repartidos en tres almacenes"
- "lleva 45 años llevando la contabilidad de pymes en Bogotá"
- "just opened a second warehouse in Manchester"
- "hired 15 engineers in the last quarter"

OUTPUT FORMAT:
Return one JSON object: {"domain": "company.com", "observation": "text here", "signal_type": "expansion", "source_quote": "the exact sentence from the research that proves this"}

For an abstention: {"domain": "company.com", "observation": "NOT_FOUND", "signal_type": null, "source_quote": null}

signal_type must be one of: expansion, hiring, leadership_change, merger_acquisition, partnership, product_launch, award, regulatory, financial, strategic_initiative, high_competition, longevity, generic

## VARIABLES:
Campaign language: {{language}}
Persona: {{persona}}
Signal priority for this persona (best first): {{signal_priority}}
Company to process:
{{company_data}}
```

---

## Input format for {{signal_priority}}

An ordered list you pass per call, taken from the persona table in the skill (Phase 6.4). For example, for a CEO-level contact:

```
company signal (group level), company signal at their site, personal signal, concrete operational detail, floor
```

and for an operations or maintenance contact:

```
personal signal, company signal at their site, concrete operational detail, floor
```

## Input format for {{company_data}}

One company per call. It should include:
```json
{
  "domain": "company.com",
  "company_name": "Company Name",
  "research": {
    "serper_results": "raw search results text",
    "employees": 150,
    "signals": ["expansion", "partnership"],
    "locations": ["Lisbon", "Porto"]
  }
}
```

## Validation

After running, check for:
- No observations containing the company name
- No observations over 15 words
- No marketing language or corporate jargon
- Each observation cites a specific, verifiable fact
- Every non-abstained observation has a `source_quote`, and that quote actually appears in the research text for that domain. A quote the model invented is worse than no quote, so verify it with a substring check rather than trusting it.
- All signal_types are valid values from the list
- No observations starting with uppercase (template adds prefix)
- Spanish output has its accents intact

## Handling NOT_FOUND

`NOT_FOUND` is a result, not an error. Never render it, never let it reach a recipient, never retry it into an answer.

1. Store it as NULL in `campaign_variables.observation`.
2. The consumer checks for NULL and drops to the next tier down, ending at the floor opener: sourced what-they-make + where, then the question (see the tier ladder in the skill, Phase 6.4). The floor never carries a claim the source does not support.
3. Track the abstention rate per batch. A rate near zero on thin research data means the model is inventing rather than abstaining, and the prompt is not working. A rate above about 30% means the research step underperformed, so fix Phase 4 rather than pushing anyway.

**Prove it goes red before you trust it.** Feed the prompt a company whose research field you have deliberately emptied, and confirm it returns `NOT_FOUND`. A validator that has never failed on known-bad input might be working or might be silently passing everything.
