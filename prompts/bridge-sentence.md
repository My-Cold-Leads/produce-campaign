# Bridge Sentence Generation Prompt

**Task:** Generate a bridge sentence that connects the observation (what you noticed about the company) to your offer (what you sell). This is the transition from "I saw X about you" to "which is why I'm reaching out."

**Model:** The model pinned for this prompt in your prompt library. For a new prompt, a Haiku-class model: bridges are tone-sensitive, which is exactly where the cheapest model costs you the most. Show a cost estimate before any paid run.

**When to use:** Phase 6 of the pipeline, after observations are generated.

**Before you use this prompt, read "Variety" below.** A model writing bridges one contact at a time repeats itself across a cohort.

---

## Prompt

```
You generate bridge sentences for cold emails. A bridge connects the observation (a fact about the company) to the reason for reaching out. It must feel natural - like a logical thought someone would have after noticing that fact.

RULES:
1. Maximum 20 words. Short bridges work best.
2. Must flow naturally from the observation. Read "I saw that [observation], [bridge]" out loud - it should sound like one thought.
3. Use plain, conversational language. Grade 5 reading level.
4. NEVER be condescending or presumptuous. Don't imply the lead is failing or missing things.
5. NEVER use corporate jargon: optimize, implement, streamline, leverage, solution, visibility
6. Never name a pain, a problem or a burden inside the bridge. The question that follows the bridge carries the pain.
7. The bridge should create curiosity or recognition, not sell.
8. End with a natural transition into a question (the template adds the question after the bridge).
9. No terminal punctuation (template handles this).
10. Output language must match the campaign language. Spanish output must carry its accents: á é í ó ú ñ ü ¿ ¡. Stripping them is a hard fail.
11. FRAME IT AS AN ACHIEVEMENT, NOT A DIAGNOSIS. The bridge is a compliment: it praises their level, ambition or standards, and leans toward something they would want to keep or get. It never says things get harder, cost more, pile up or slip out of control. "Growing that fast, you'll want to keep everything in view" is right. "You are growing fast so your fleet maintenance must be falling behind" is not.
12. If the observation is the floor template (no company-specific fact), the bridge must also stay generic. Do not invent a company-specific consequence to bridge from a generic opener.
13. Do not repeat a word from the observation.

ABSTENTION:
Return "NOT_FOUND" as the bridge when the observation is itself NOT_FOUND, or when
you cannot connect the observation to the offer without inventing a fact about the
company. A generic bridge is fine. An invented one is not.

BRIDGE TYPES (pick the most natural fit):

1. GROWTH bridge: "[observation], [compliment on the momentum] + [what they would want]"
   - "está abriendo un almacén en Valencia, y con ese ritmo seguro que queréis tener cada camión a punto"

2. SCALE bridge: "[observation], and at that level [what they would want]"
   - "mueve 60 camiones desde cuatro almacenes, y a ese nivel imagino que queréis que cada revisión llegue a tiempo"

3. MOMENT bridge: "[observation], and at a moment like this [what they would want]"
   - "acaba de cerrar una ronda de inversión, y en un momento así seguro que queréis que la flota esté siempre lista"

4. TRACK-RECORD bridge: "[observation], and with that track record [what they would want]"
   - "lleva 30 años en el sector, y con esa trayectoria seguro que queréis mantener el nivel que os ha traído hasta aquí"

BAD EXAMPLES:
- "which must create significant operational challenges for your team" (corporate speak, condescending)
- "I imagine this means you're struggling to keep up" (presumptuous)
- "y con ese volumen cada revisión de la flota cuesta tiempo" (names a burden)
- "y en fases así el control de gastos se complica" (warning, not compliment)
- "this suggests an opportunity to optimize your workflow" (selling, not bridging)
- "and I was wondering if you've considered how AI could help" (jumping to pitch)

GOOD EXAMPLES:
- "y con ese ritmo de crecimiento seguro que queréis tenerlo todo a la vista"
- "and at that pace you'll want every truck ready to roll each morning"
- "así que imagino que queréis que cada vehículo nuevo salga a la ruta a punto"

OUTPUT FORMAT:
Return one JSON object: {"domain": "company.com", "bridge": "text here", "bridge_type": "growth"}

bridge_type must be one of: growth, scale, moment, track_record

## VARIABLES:
Campaign language: {{language}}
Company and its observation:
{{observation_data}}
```

---

## Input format for {{observation_data}}

One company per call. Save each result the moment it returns (see "durable writes" in the skill), so one failed call costs one row, not the run.

```json
{
  "domain": "company.com",
  "observation": "acaba de abrir un tercer almacén en Monterrey",
  "signal_type": "expansion",
  "sector": "logistics",
  "offer_summary": "a scheduling tool that keeps fleet maintenance on time for logistics companies"
}
```

The `offer_summary` is critical - the bridge must connect the observation to YOUR specific offer, not to a generic challenge.

## Variety

Each call only sees one company, so across a cohort the model settles on a few favourite sentences and repeats them hundreds of times. To a spam filter that is one template.

Pick one of two approaches:

1. **A pool.** Build a large, varied, pre-approved pool of bridge parts (for example a signal-specific referback, a connector and a tail), all achievement-framed, and pick deterministically per contact. Same contact, same bridge; hundreds of distinct sentences across the cohort; no AI cost.
2. **Generate, then check.** If you generate per contact with this prompt, run the 15% copy variation check (section 7.1 of the skill) across the whole cohort's bridges before push, and rewrite or re-pick any bridge above the cap.

## Validation

After running, check for:
- No bridges over 20 words
- No corporate jargon
- No condescending language, no named pain or burden, and no diagnosis the lead did not ask for
- Each bridge flows naturally from its observation
- No bridge asserts a company-specific fact that is absent from its observation
- No bridge sentence reaches more than 15% of the cohort (section 7.1)
- Spanish output has its accents intact
- Read 10 random "[observation], [bridge]" combos out loud - do they sound human?
