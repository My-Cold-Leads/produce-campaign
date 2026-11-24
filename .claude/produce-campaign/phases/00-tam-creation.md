<!-- Part of the produce-campaign skill. Index and always-on rules: .claude/commands/produce-campaign.md -->

## Phase 0: TAM Creation (First-Time Setup)

**Skip this phase if you already have companies and contacts in your database.**

This skill is focused on campaign production - taking a list of companies and contacts through to a launched, quality-checked campaign. It's not a deep-dive on TAM strategy or list building (we have a whole separate process for that). But you need a solid list before any of the other phases work, so here's a quick version to get you started.

### 0.1 - Define Your ICP

Before sourcing companies, define who you're targeting:
- **Industry/sector** - what types of companies? (e.g., accounting firms, logistics, SaaS, hotels, law firms, manufacturing)
- **Company size** - employee count range? (e.g., 50-500 employees)
- **Geography** - which countries, regions, or cities?
- **Key decision makers (KDMs)** - who are you emailing? (e.g., CEO, Head of Finance, Operations Director)
- **Exclusions** - who do you NOT want? (e.g., companies under 10 employees, government agencies)

Document this in your client config file. Every sourcing decision flows from the ICP.

**If you are qualifying companies against the ICP with a model rather than by
hand, iterate that prompt properly before you run it.** ICP qualification is a
classifier, and a classifier that is 85% right silently poisons every phase after
it - you enrich, research and write to companies that were never a fit, and you
pay for all of it. See [iterative-prompting.md](iterative-prompting.md): one
anchor, rounds of 10 fresh samples, lock on two consecutive zero-edit rounds, then
walk the sample-size ladder before the full batch.

### 0.2 - Source Companies

Use one or more of these tools to build your company list:

| Source | Best for | How to use |
|--------|----------|-----------|
| **Apollo** | B2B companies with employee filters, industry, location | Search with your ICP filters, export company list as CSV |
| **Prospeo** | Finding companies by domain or LinkedIn | Company search + enrichment |
| **Google Maps / local directories** | Local businesses (restaurants, shops, workshops) | Search by category + location, extract business websites |
| **LinkedIn Sales Navigator** | Targeted account lists with advanced filters | Build account list, export |
| **Industry directories** | Niche markets with specialized directories | Scrape or manually collect |
| **Your existing network** | Warm leads, referrals, past clients | Export from CRM |

**After sourcing, save ALL companies to your database immediately:**
```sql
INSERT INTO companies (client_name, domain, company_name, sector, city, country)
VALUES ('{CLIENT}', 'company.com', 'Company Name', 'logistics', 'Lisbon', 'Portugal')
ON CONFLICT (client_name, domain) DO NOTHING;
```

Aim for 3-5x more companies than you need for your first campaign. You'll lose some at every step (no contacts found, invalid emails, DNC'd, etc.).

### 0.3 - Find Contacts at Those Companies

For each company, find ALL the decision makers matching your KDM personas - not just one. A company you mine for one person is a company you will pay to mine again later.

**Five sources, run at the same time over the whole company list.** Never one after another, and never only on the companies the previous source missed. Each source finds people the others miss.

| # | Source | What it finds | How |
|---|--------|---------------|-----|
| 1 | **Prospeo** | Named people with LinkedIn, current employer refreshed often | People search by company domain + person country. |
| 2 | **Apollo** | The widest list of names at a company | People search is free. Names come back partly masked, so use it to size and find, then enrich the ones you keep. |
| 3 | **AI search on Google** | Decision makers the databases don't have, especially at small and mid-size companies | Role-targeted Google queries (e.g. via [Serper](https://serper.dev)), then Claude reads the results and the pages it finds. See "AI search" below. |
| 4 | **The company's own website** | Names on team, about and contact pages, plus the company's email format | Claude reads the site (homepage, about, team, contact). The email format lets you build and verify a candidate email for free later. |
| 5 | **Local and niche databases** | Companies and people the big databases cover badly | Sector directories, trade association member lists, trade fair and event exhibitor lists, any niche listing that fits your ICP. Scrape them and match to your company list. |

**AI search - how to run it with Claude.** Per company and per persona:
- **Q1 (anchor the company):** `site:linkedin.com/company "{company_name}" OR {company_domain}`
- **Q2 (role-targeted people):** `site:linkedin.com/in ("{company_name}" OR {company_domain}) (director OR head OR responsable OR jefe OR manager) ({persona keywords})` - swap the role and keyword cluster for each persona (e.g. CEO / Director General for P1, plant or operations director for P2).
- **Q3 (fallback, broader roles):** the same company anchor with a wider set of titles for that persona.
- **Cost cap:** max 3 searches and 2 profile reads per company, stop at 1-2 verified people.
- **Verify before you keep:** the page Claude read must show the person CURRENTLY works there in that role. Search snippets only find candidate pages; they are never proof. If Claude can't quote it from a page it actually read, it saves nothing and says so.

**Filter by person country, NOT by job title.** Search by company domain + the country where the person works (this drops a multinational's staff abroad). Do NOT use the vendors' title, seniority or department filters: real titles are messy ("Jefe de Mantenimiento", "Director Planta", two roles in one line) and those filters silently throw away real decision makers. Pull broadly, then classify locally.

**Classify every title with AI, including the long tail.** Run each person's title through one classifier prompt that maps it to your personas (P1, P2, ... or "not a decision maker"). Build and lock that prompt with [iterative prompting](./iterative-prompting.md), and test it on a few known titles before every run. Don't skip titles that "sound junior" - that tail is where many real decision makers sit.

**Then the order that saves the money:**

| Step | You have | You want | Why this order |
|------|----------|----------|----------------|
| **1. Discover** (the five sources above) | A company | Everyone who could be a decision maker | Most of this is free or cheap. |
| **2. Dedupe** | Search results | Only the people you don't have yet | This is the step that saves the money. Match on the LinkedIn profile slug (the part after `/in/`, decoded), or name + company when there is no LinkedIn. |
| **3. Enrich** | A named person with no email | Their verified email | **Prospeo first**, then Apollo match, then Icypeas or Findymail, then verify. Only now do you pay. |

**The incident behind this:** running a paid search-first tool in the discovery slot cost us roughly 4x what it should have, because most of the spend went on people already in our database.

**90-day cohort cooldown.** Do not re-run discovery over the same company list within 90 days. It returns about 5% new finds at full cost. Record the date you last ran discovery per company (`last_ai_contact_search_date`) and filter on it.

**A person found without an email is still a find.** Save the contact with a null email and send it to the waterfall in Phase 3. Discarding it means paying to discover them again next quarter.

**Save ALL contacts to your database, with every field the source returned** (title, LinkedIn, country, source):
```sql
INSERT INTO contacts (client_name, email, first_name, last_name, job_title, company_domain, kdm)
VALUES ('{CLIENT}', 'maria@company.com', 'Maria', 'Garcia', 'Head of Operations', 'company.com', 'P1')
ON CONFLICT (client_name, LOWER(email)) WHERE email IS NOT NULL DO NOTHING;
```
The conflict target is the unique index `idx_contacts_client_email_unique` from `setup/schema.sql`. Without naming it, `ON CONFLICT DO NOTHING` has nothing to conflict with and every re-run inserts the same people again. Contacts saved with a null email are deduped by you (name + company domain) before insert.

**Assign KDM personas** (P1, P2, P3, etc.) from the classifier above. P1 = your primary decision maker, P2 = secondary, etc. Define what each persona means for YOUR ICP in the client config.

### 0.4 - Verify Emails

Contacts without verified emails cannot be pushed to campaigns. See Phase 3 for the full email validation process.

At minimum, run all found emails through a verification service (Prospeo, MillionVerifier, or BounceBan) and update the `email_status` field. Only `valid` and `deliverable_catchall` emails proceed.

### 0.5 - TAM Health Check

After sourcing, check your numbers:
```
Companies sourced: X
Contacts found: X (X% of companies have at least one contact)
Emails verified: X valid + X catchall = X contactable
Coverage: X contactable / X companies = X%
```

If contactable coverage is below 40%, go back and try additional sources before proceeding. The pipeline needs volume to work - a campaign with 50 contacts won't give you meaningful data.
