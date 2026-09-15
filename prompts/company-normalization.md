# Company Name Normalization Prompt

**Task:** Clean raw company names into professional Title Case format for use in email subject lines and body copy.

**Model:** The model pinned for this prompt in your prompt library. For a new prompt, the cheapest capable small model (GPT-4o-mini class). This is a near-deterministic task - but the output lands in subject lines, so verify the batch rather than assuming. Show a cost estimate before any paid run.

**When to use:** Before generating any email variables. Raw company names from databases often come as domains, ALL CAPS, or inconsistent formatting. This prompt fixes that.

**Reuse first:** a normalized name is a durable fact. If your database already has one for a company, use it. Send only the companies whose normalized name is empty.

**Batch size:** 50 companies at a time

---

## Prompt

```
You are a company name normalizer. Your job is to convert raw company names into clean, professional Title Case format suitable for use in business email subject lines.

RULES:
1. Output in Title Case (capitalize first letter of each major word)
2. Strip legal suffixes: S.A., S.L., S.L.U., S.A.S., S.A. de C.V., Ltd, Plc, LLC, Inc., GmbH, AG, B.V.
3. Strip place qualifiers that are not part of how the company is known: trailing country or region tags such as "(Chile)", "Iberia", "Europe", "España".
4. NEVER INVENT AN INITIALISM. A short form is allowed only when those exact letters already appear as a token in the source name ("ACME Iberia S.L." -> "ACME"). If the source spells the words out, keep the words ("Contenedores Ejemplo del Sur S.A." -> "Contenedores Ejemplo del Sur", never "CES"). Being a real, well-known acronym is not enough - if the token is not in the source, do not use it.
5. Acronym tokens that ARE in the source stay uppercase: IBM, BMW, SAP, DHL, IKEA
6. Articles, prepositions, and conjunctions stay lowercase unless first word: de, del, y, e, la, las, los, el, the, and, of, for
7. If input is a domain (contains ".com", ".es", etc.), extract the company name from the domain and Title Case it, only when the words are clearly readable. Example: "acmelogistics.com" -> "Acme Logistics"
8. If the company name contains "Group", "Grupo", "Holdings" - keep it. These are part of how the company is known.
9. If unsure about a brand's casing, preserve the original casing.
10. Accents: reproduce the brand exactly as the company writes it. If the real brand carries an accent, keep it (Telefónica, Iberdrola, Acciona, Mahou-San Miguel). If a source stripped the accent, restore it (telefonica -> Telefónica). Never invent an accent the real brand does not use. Getting this wrong is visible to every recipient, because this field lands in the subject line.
11. Never output a raw domain as the company name. If you cannot produce a name you would be willing to put in a subject line, return "NOT_FOUND" rather than guessing. A blank is recoverable; a wrong company name in a subject line is not.

OUTPUT FORMAT:
Return a JSON array of objects: [{"original": "input", "normalized": "Output"}]
Do not add any explanation. Just the JSON.

## VARIABLES:
Companies to normalize:
{{company_list}}
```

---

## Example input/output

Input: `["ACME INDUSTRIES S.L.", "grupo acme", "BMW", "la casa del cafe s.a.", "steelworks.com", "INDUSTRIAS MARTINEZ Y ASOCIADOS", "telefonica", "CONTENEDORES EJEMPLO DEL SUR S.A.", "ACME Iberia S.L.", "xk7q2.net"]`

Output:
```json
[
  {"original": "ACME INDUSTRIES S.L.", "normalized": "Acme Industries"},
  {"original": "grupo acme", "normalized": "Grupo Acme"},
  {"original": "BMW", "normalized": "BMW"},
  {"original": "la casa del cafe s.a.", "normalized": "La Casa del Café"},
  {"original": "steelworks.com", "normalized": "Steelworks"},
  {"original": "INDUSTRIAS MARTINEZ Y ASOCIADOS", "normalized": "Industrias Martínez y Asociados"},
  {"original": "telefonica", "normalized": "Telefónica"},
  {"original": "CONTENEDORES EJEMPLO DEL SUR S.A.", "normalized": "Contenedores Ejemplo del Sur"},
  {"original": "ACME Iberia S.L.", "normalized": "ACME"},
  {"original": "xk7q2.net", "normalized": "NOT_FOUND"}
]
```

## Validation

After running, check for:
- Zero domains remaining as company names (no ".com", ".es", ".co.uk" in output)
- Zero legal suffixes remaining (S.L., S.A., Ltd, GmbH, Inc...)
- Zero invented initialisms: every all-capitals output token must appear in the source name
- Zero ALL CAPS outputs (except acronym tokens present in the source)
- Zero all-lowercase outputs
- Spanish names carry their accents
- `NOT_FOUND` is stored as empty, never written into a subject line

Run these as SQL against your companies table, not by eye. A raw domain or an ALL CAPS name in a subject line is one of the few defects every single recipient sees:

```sql
-- Must return zero rows
SELECT domain, normalized_name FROM companies
WHERE normalized_name ~ '\.[a-z]{2,4}$'                                  -- still a domain
   OR normalized_name ~* '\m(s\.?l\.?u?|s\.?a\.?|ltd|plc|gmbh|inc|llc)\.?$' -- legal suffix left
   OR normalized_name ~ '^[A-Z0-9 .,&-]+$'   -- ALL CAPS (acronyms show up here too - confirm each token is in the source name)
   OR normalized_name = LOWER(normalized_name);
```
