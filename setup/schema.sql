-- Minimal Supabase schema for produce-campaign
-- Run this in your Supabase SQL editor to create the required tables.
--
-- Safe to run more than once. Every table uses CREATE TABLE IF NOT EXISTS and
-- every column added after the first release uses ADD COLUMN IF NOT EXISTS, so
-- re-running this file upgrades an older install instead of failing.
--
-- MULTI-CLIENT: every table that holds client data carries client_name. If you
-- only ever run one client, leave it at its default and every query still works.
-- Every query in the skill filters on client_name = '{CLIENT}'.

-- Companies: your target account list
CREATE TABLE IF NOT EXISTS companies (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  client_name TEXT NOT NULL DEFAULT 'default',  -- which client this row belongs to
  domain TEXT NOT NULL,
  company_name TEXT,
  normalized_name TEXT,  -- Title Case, cleaned (e.g., "Acme Industries" not "ACME INDUSTRIES" or "acme.com")
  sector TEXT,
  employee_count INTEGER,
  city TEXT,
  country TEXT,
  personalization_data JSONB DEFAULT '{}'::jsonb,  -- research signals, raw SERP data, etc.
  last_ai_contact_search_date TIMESTAMPTZ,  -- when contact discovery last ran for this company (Phase 1.3)
  do_not_contact BOOLEAN DEFAULT false,
  dnc_source TEXT,  -- why this company is DNC'd
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(client_name, domain)
);

-- Contacts: people at those companies
-- company_domain is informational. The skill always joins contacts to companies
-- on the email domain plus client_name (Phase 2.3), because this field is often empty.
CREATE TABLE IF NOT EXISTS contacts (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  client_name TEXT NOT NULL DEFAULT 'default',
  email TEXT,
  email_status TEXT,  -- 'valid', 'deliverable_catchall', 'invalid', 'catch_all', NULL
  email_searched_at TIMESTAMPTZ,  -- when the email was last found or verified (Phase 3.0 / 3.1)
  first_name TEXT,
  last_name TEXT,
  job_title TEXT,
  linkedin_url TEXT,
  company_domain TEXT,
  kdm TEXT,  -- persona code: P1, P2, P3, etc.
  do_not_contact BOOLEAN DEFAULT false,
  assigned_campaign TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Campaign variables: per-contact personalized fields
CREATE TABLE IF NOT EXISTS campaign_variables (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  client_name TEXT NOT NULL DEFAULT 'default',
  contact_id UUID REFERENCES contacts(id),
  company_id UUID REFERENCES companies(id),
  campaign_id TEXT NOT NULL,  -- your Smartlead campaign ID
  persona TEXT,
  observation TEXT,  -- the personalized opening line
  obs_short TEXT,    -- shorter version for E2
  signal_type TEXT,  -- 'expansion', 'hiring', 'merger_acquisition', etc.
  bridge TEXT,       -- connects observation to offer
  bullet1 TEXT,
  bullet2 TEXT,
  bullet3 TEXT,
  proof_sentence TEXT,  -- social proof sentence
  ps_line TEXT,      -- PS line with different value angle
  model_used TEXT,   -- which AI model generated these
  generation_status TEXT DEFAULT 'pending',
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(contact_id, campaign_id)
);

-- Outreach log: tracks who was contacted and when
--
-- TWO TIMESTAMPS, ONE COOLDOWN. Write loaded_date AT PUSH TIME (the moment you
-- send leads to the platform), not after the platform sends. first_sent_date is
-- backfilled later by your sync job. Every cooldown check must read
-- COALESCE(first_sent_date, loaded_date) so a lead that is queued but not yet
-- sent still counts as contacted. Waiting for the send to log creates a window
-- (up to 24h) where the same person can be loaded twice and where your
-- available-contact counts read high.
CREATE TABLE IF NOT EXISTS outreach_log (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  client_name TEXT NOT NULL DEFAULT 'default',
  contact_id UUID REFERENCES contacts(id),  -- may be NULL for a lead pushed from a file
  email TEXT NOT NULL,
  campaign_id TEXT,
  campaign_name TEXT,
  loaded_date TIMESTAMPTZ DEFAULT NOW(),  -- written at push time, never later
  first_sent_date TIMESTAMPTZ,  -- backfilled by your sync job after the platform sends
  signal_type TEXT,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Campaign copy versions: version history for email sequences
CREATE TABLE IF NOT EXISTS campaign_copy_versions (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  client_name TEXT NOT NULL DEFAULT 'default',
  campaign_id TEXT NOT NULL,
  campaign_label TEXT,
  sequence_step INTEGER,  -- 1 = E1, 2 = E2, etc.
  variant TEXT,  -- 'A', 'B'
  subject TEXT,
  body_html TEXT,
  version INTEGER DEFAULT 1,
  change_note TEXT,
  source TEXT,  -- who or what wrote this version: 'claude_code', 'manual', etc.
  pushed BOOLEAN DEFAULT false,  -- true once the copy is live on the sending platform
  pushed_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Prompt library: store and iterate your prompts
CREATE TABLE IF NOT EXISTS prompt_library (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  client_name TEXT NOT NULL DEFAULT 'default',
  task_type TEXT NOT NULL,  -- 'observation', 'bridge', 'normalization', etc.
  prompt_name TEXT,
  prompt_text TEXT,
  model TEXT,  -- 'gpt-4o-mini', 'claude-haiku-4-5', etc.
  tags TEXT[],
  notes TEXT,
  required_inputs JSONB,  -- fields that must be non-empty before this prompt runs
  input_sanitization_rules JSONB,  -- how inputs are cleaned before the model sees them
  output_validation_rules JSONB,  -- rules for rejecting bad outputs
  usage_count INTEGER DEFAULT 0,
  last_used_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Campaign responses: replies pulled back from your sending platform
-- Used by the in-flight check (Phase 2.4) and the targeting feedback loop (Phase 13)
CREATE TABLE IF NOT EXISTS campaign_responses (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  lead_email TEXT NOT NULL,
  campaign_id TEXT NOT NULL,
  sequence_step INTEGER,  -- which email got the reply: 1 = E1, 2 = E2
  sequence_completed BOOLEAN DEFAULT false,  -- false = still in flight, do not re-load
  reply_category TEXT,  -- 'interested', 'meeting_booked', 'forwarded_internally', 'not_interested', 'wrong_person', 'unsubscribe'
  reply_text TEXT,
  replied_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  UNIQUE(lead_email, campaign_id)
);

-- Email waterfall queue: one row per contact moving through your finding/verification providers
-- Used by Phase 3. Track which provider produced the result so you can measure yield per tool.
CREATE TABLE IF NOT EXISTS email_waterfall_queue (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  contact_id UUID REFERENCES contacts(id),
  batch_id TEXT,  -- group a run so you can monitor it: '{client}-2026-08'
  step TEXT DEFAULT 'pending',  -- 'pending', 'searching', 'verifying', 'done', 'not_found'
  provider_attempted TEXT[],  -- every provider tried, in order
  provider_succeeded TEXT,  -- the one that returned the email
  email_found TEXT,
  email_status TEXT,
  attempts INTEGER DEFAULT 0,
  last_error TEXT,  -- keep the response body, not just the status code
  not_found_until TIMESTAMPTZ,  -- do not re-search this contact before this date (60 days is a sane default)
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Campaign push log: an append-only record of every push
-- Used by Phase 8.1. This is what lets you answer "what did we send that batch?" months later.
CREATE TABLE IF NOT EXISTS campaign_push_log (
  id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
  client_name TEXT NOT NULL DEFAULT 'default',
  campaign_id TEXT NOT NULL,
  campaign_label TEXT,
  action TEXT NOT NULL,  -- 'leads_pushed', 'copy_updated', 'campaign_launched', 'campaign_paused'
  detail JSONB DEFAULT '{}'::jsonb,  -- {"attempted": N, "succeeded": N, "failed": N, "failed_ids": [...]}
  created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Upgrade path for installs created from an earlier version of this file.
-- CREATE TABLE IF NOT EXISTS does not add columns to a table that already exists.
ALTER TABLE companies ADD COLUMN IF NOT EXISTS client_name TEXT NOT NULL DEFAULT 'default';
ALTER TABLE companies ADD COLUMN IF NOT EXISTS last_ai_contact_search_date TIMESTAMPTZ;
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS client_name TEXT NOT NULL DEFAULT 'default';
ALTER TABLE contacts ADD COLUMN IF NOT EXISTS email_searched_at TIMESTAMPTZ;
ALTER TABLE campaign_variables ADD COLUMN IF NOT EXISTS client_name TEXT NOT NULL DEFAULT 'default';
ALTER TABLE campaign_variables ADD COLUMN IF NOT EXISTS company_id UUID REFERENCES companies(id);
ALTER TABLE campaign_variables ADD COLUMN IF NOT EXISTS proof_sentence TEXT;
ALTER TABLE outreach_log ADD COLUMN IF NOT EXISTS client_name TEXT NOT NULL DEFAULT 'default';
ALTER TABLE outreach_log ADD COLUMN IF NOT EXISTS contact_id UUID REFERENCES contacts(id);
ALTER TABLE campaign_copy_versions ADD COLUMN IF NOT EXISTS client_name TEXT NOT NULL DEFAULT 'default';
ALTER TABLE campaign_copy_versions ADD COLUMN IF NOT EXISTS source TEXT;
ALTER TABLE campaign_copy_versions ADD COLUMN IF NOT EXISTS pushed BOOLEAN DEFAULT false;
ALTER TABLE prompt_library ADD COLUMN IF NOT EXISTS client_name TEXT NOT NULL DEFAULT 'default';
ALTER TABLE prompt_library ADD COLUMN IF NOT EXISTS input_sanitization_rules JSONB;
ALTER TABLE campaign_push_log ADD COLUMN IF NOT EXISTS client_name TEXT NOT NULL DEFAULT 'default';
-- An older install has UNIQUE(domain) on companies and a foreign key from
-- contacts.company_domain. Both still work for a single client. To hold the same
-- domain for two clients, drop that constraint and that foreign key; the unique
-- index below keeps one row per client per domain.

-- Indexes for common queries
CREATE UNIQUE INDEX IF NOT EXISTS idx_companies_client_domain ON companies(client_name, domain);
CREATE INDEX IF NOT EXISTS idx_companies_domain ON companies(domain);
CREATE INDEX IF NOT EXISTS idx_companies_discovery ON companies(client_name, last_ai_contact_search_date);
CREATE INDEX IF NOT EXISTS idx_contacts_client ON contacts(client_name);
CREATE INDEX IF NOT EXISTS idx_contacts_email ON contacts(email);
CREATE INDEX IF NOT EXISTS idx_contacts_email_domain ON contacts(client_name, (SPLIT_PART(email, '@', 2)));
CREATE INDEX IF NOT EXISTS idx_contacts_company_domain ON contacts(company_domain);
CREATE INDEX IF NOT EXISTS idx_contacts_kdm ON contacts(client_name, kdm);
CREATE INDEX IF NOT EXISTS idx_contacts_email_status ON contacts(email_status);
CREATE INDEX IF NOT EXISTS idx_contacts_assigned_campaign ON contacts(client_name, assigned_campaign);
CREATE INDEX IF NOT EXISTS idx_campaign_variables_contact ON campaign_variables(contact_id);
CREATE INDEX IF NOT EXISTS idx_campaign_variables_campaign ON campaign_variables(campaign_id);
CREATE INDEX IF NOT EXISTS idx_campaign_variables_client ON campaign_variables(client_name);
CREATE INDEX IF NOT EXISTS idx_outreach_log_email ON outreach_log(email);
CREATE INDEX IF NOT EXISTS idx_outreach_log_contact ON outreach_log(contact_id);
CREATE INDEX IF NOT EXISTS idx_outreach_log_cooldown ON outreach_log(client_name, email, (COALESCE(first_sent_date, loaded_date)) DESC);
CREATE INDEX IF NOT EXISTS idx_outreach_log_contact_cooldown ON outreach_log(client_name, contact_id, (COALESCE(first_sent_date, loaded_date)) DESC);
CREATE INDEX IF NOT EXISTS idx_copy_versions_campaign ON campaign_copy_versions(client_name, campaign_id);
CREATE INDEX IF NOT EXISTS idx_prompt_library_task ON prompt_library(client_name, task_type);
CREATE INDEX IF NOT EXISTS idx_campaign_responses_email ON campaign_responses(lead_email);
CREATE INDEX IF NOT EXISTS idx_campaign_responses_campaign ON campaign_responses(campaign_id);
CREATE INDEX IF NOT EXISTS idx_waterfall_batch_step ON email_waterfall_queue(batch_id, step);
CREATE INDEX IF NOT EXISTS idx_waterfall_contact ON email_waterfall_queue(contact_id);
CREATE INDEX IF NOT EXISTS idx_push_log_campaign ON campaign_push_log(client_name, campaign_id);

-- Enable RLS (Row Level Security) on all tables
-- IMPORTANT: Configure your own RLS policies based on your auth setup
ALTER TABLE companies ENABLE ROW LEVEL SECURITY;
ALTER TABLE contacts ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign_variables ENABLE ROW LEVEL SECURITY;
ALTER TABLE outreach_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign_copy_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE prompt_library ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign_responses ENABLE ROW LEVEL SECURITY;
ALTER TABLE email_waterfall_queue ENABLE ROW LEVEL SECURITY;
ALTER TABLE campaign_push_log ENABLE ROW LEVEL SECURITY;
