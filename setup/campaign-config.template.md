# Campaign Config - {CLIENT}

Copy this file once per client and fill in every section before running `/produce-campaign`. Phase 1.1 reads it and refuses to start if a required section is empty, and Phase 6.7 assembles the deterministic fields from its lookup tables.

This file is **reference data**: who you target, what you say to whom, which campaigns and domains exist. It is not a diary. "What happened and when" belongs in your database (the push log, the gate evidence), not here. See "Context Window Survival" in the skill.

Every example row below is made up. Replace all of them.

Last updated: 2026-01-01

---

## 1. ICP

Who you are targeting. Every sourcing and exclusion decision flows from this. Keep it short and testable: someone else should be able to decide whether a company fits by reading it.

| Field | Value |
|-------|-------|
| Sectors | logistics, warehousing, freight forwarding |
| Company size | 50-500 employees |
| Geography | Spain, Portugal |
| Exclusions | government bodies, companies under 10 employees, pure software resellers |
| Accept catchall emails | true |
| Freemail policy (Phase 4.5) | review (large companies) / keep (small businesses) |
| Campaign language | Spanish |

**Offer (Phase 6.0):** the concrete thing the lead gets. Something with a noun.

> Example: a free audit of how many fleet maintenance checks are still scheduled by hand, with a benchmark against similar fleets.

---

## 2. Personas

One row per persona code stored in `contacts.kdm`. Phase 2.1 reads the code; it never re-classifies from the job title. The signal priority column feeds the observation prompt (Phase 6.4).

| kdm | Persona | Example titles | Signal priority (best first) |
|-----|---------|----------------|------------------------------|
| P1 | Managing Director | CEO, Director General | company signal (group) -> company signal (site) -> personal signal -> concrete detail -> floor |
| P2 | Operations Director | Director de Operaciones | personal signal -> company signal (site) -> concrete detail -> floor |
| P3 | Fleet Manager | Jefe de Flota | personal signal -> company signal (site) -> concrete detail -> floor |
| P0 | Out of ICP | Intern, Student | never pushed |

---

## 3. Industry map

Maps every raw `companies.sector` value in your database to the sector label your lookup tables use. Phase 1.1 checks that every sector in the database appears here. An unmapped sector means a contact with no bullets and no social proof.

| Raw sector value | Mapped sector |
|------------------|---------------|
| transport | logistics |
| freight forwarding | logistics |
| warehousing and storage | warehousing |

---

## 4. Lookup tables: persona x sector

Every persona crossed with every mapped sector needs a row. Phase 1.1 fails on a missing combination. These cells are the deterministic parts of the copy; the AI only writes the per-contact fields.

| Persona | Sector | Angle | E1 question | Template variant |
|---------|--------|-------|-------------|------------------|
| P1 | logistics | save money | ¿cuánto os cuesta cada camión parado por una revisión tardía? | E1-A |
| P2 | logistics | save time | ¿cuántas revisiones seguís programando a mano? | E1-B |
| P3 | warehousing | reduce risk | ¿cómo sabéis hoy qué carretilla toca revisar esta semana? | E1-B |

---

## 5. Social proof table

Anonymous outcomes only. The email never names the case study company (see "Case Studies / Social Proof" in the skill). You may keep the real reference name here for your own records. Feeds `proof_line_1`, `proof_line_2`, `proof_detail` and `outcome_tail` in Phase 6.7.

| Sector | Persona | proof_line_1 | proof_line_2 | proof_detail | outcome_tail |
|--------|---------|--------------|--------------|--------------|--------------|
| logistics | P1 | una empresa de transporte con 80 camiones | un operador logístico del norte | dejó de programar revisiones a mano | en tres meses |
| warehousing | P3 | un almacén de frío en Valencia | una empresa de paquetería regional | redujo las averías por revisiones olvidadas | en el primer trimestre |

`proof_line_1` and `proof_line_2` must differ on every row (checked in Phase 7.5).

---

## 6. Proof sentence table

One pre-approved sentence per sector and persona, used as `proof_sentence`. Keep several per cell if you can, so the 15% variation check in 7.1 has room.

| Sector | Persona | proof_sentence |
|--------|---------|----------------|
| logistics | P2 | Ayudamos a una empresa de transporte parecida a tener todas las revisiones en un mismo calendario. |
| warehousing | P3 | Un almacén de tamaño similar dejó de perseguir revisiones por correo en unas semanas. |

---

## 7. Bullets table

The three E2 bullets per sector and persona, stated as what the reader gets. If your template expects a bullet prefix, store the text without it and prepend it at push time (Phase 7.5).

| Sector | Persona | bullet1 | bullet2 | bullet3 |
|--------|---------|---------|---------|---------|
| logistics | P2 | cada revisión avisa sola antes de vencer | ves toda la flota en una sola pantalla | el taller recibe la cita sin llamadas |
| warehousing | P3 | sabes qué equipo toca revisar cada semana | los partes quedan guardados con fecha | nadie depende de una hoja de cálculo |

---

## 8. Client scripts

Client-specific scripts that must run as part of every push (Phase 1.1c). List them with what they do. Every one still pushes through `scripts/push-safe.py`.

| Script | What it does | When it runs |
|--------|--------------|--------------|
| scripts/example-client-cap.py | caps any single email domain at 5 recipients per push | before the push preview |

Write "none" if there are none, so the check has an answer.

---

## 9. Status and next move

One or two lines: where this client is right now and the very next action. Phase 1.1 reads it aloud at session start. Overwrite it; do not append history here.

> Example: Copy for the spring cohort approved. Next move: generate variables for P2 and P3.

---

## 10. Campaign roster

Every campaign for this client, with its sending platform ID. Phases 8, 10 and 11 update lead counts and status.

| Campaign label | Campaign ID | Persona | Sector | Leads | Status | Launched |
|----------------|-------------|---------|--------|-------|--------|----------|
| acme-2026-09-p2 | 1234567 | P2 | logistics | 0 | DRAFT | - |
| acme-2026-09-p3 | 1234568 | P3 | warehousing | 0 | DRAFT | - |

Status values: DRAFT, LOADED, LIVE, PAUSED, COMPLETED.

---

## 11. Domain health

Sending domains assigned to this client. One domain per campaign (Phase 5). Phase 11 marks launched domains as PRIMARY.

| Domain | Campaign label | Reply rate | Bounce rate | Role |
|--------|----------------|------------|-------------|------|
| acme-example-mail.com | acme-2026-09-p2 | - | - | PRIMARY |
| acme-example-send.com | acme-2026-09-p3 | - | - | PRIMARY |

Pause a domain whose bounce rate goes over 3% (Phase 3.4).

---

## 12. Copy status

One row per sequence step per campaign. Nothing is pushed unless its row says APPROVED (Phase 7.7).

| Campaign label | Step | Variant | Status | Approved by | Copy fingerprint |
|----------------|------|---------|--------|-------------|------------------|
| acme-2026-09-p2 | E1 | A | APPROVED | client, "looks good, go" | 3f9a... |
| acme-2026-09-p2 | E2 | A | DRAFT | - | - |

Status values: DRAFT, IN REVIEW, APPROVED, LOADED.

---

## 13. Signal performance (Phase 13)

Filled in after live data comes back. Illustrative example (made-up numbers):

| Signal | Campaigns tested | Avg positive rate | Notes |
|--------|------------------|-------------------|-------|
| expansion | 3 batches | 2.0% | best performer |
| generic | 3 batches | 0.5% | invest in research instead |
