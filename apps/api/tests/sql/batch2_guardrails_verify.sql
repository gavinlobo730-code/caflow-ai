-- Batch 2 (Amendment v1.1) RLS guardrail verification harness.
-- Run by tests/test_batch2_guardrails_migration.py, which splices the REAL
-- migration files into the markers below (073 + 074 forward, then 074 + 073
-- rollback). Proves the RESTRICTIVE G1 policies hide the internal client's row
-- and its financial rows from non-Partners, while Partners retain full access,
-- and that removing 074 restores visibility (i.e. 074 is what enforces G1).
\set ON_ERROR_STOP on
\echo '=== BATCH 2 RLS VERIFICATION START ==='

DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
DROP SCHEMA IF EXISTS auth CASCADE;   CREATE SCHEMA auth;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='anon')          THEN CREATE ROLE anon NOLOGIN; END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='service_role')  THEN CREATE ROLE service_role NOLOGIN; END IF;
END $$;
GRANT USAGE ON SCHEMA public TO authenticated, anon, service_role;
GRANT USAGE ON SCHEMA auth   TO authenticated, anon, service_role;

CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid AS $$
  SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$ LANGUAGE sql STABLE;

-- Prerequisite tables (clients created WITHOUT is_internal; 073 adds it).
CREATE TABLE firms (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), name TEXT NOT NULL, email TEXT NOT NULL
);
CREATE TABLE clients (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  client_name TEXT NOT NULL,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('Proprietorship','Partnership','LLP','Private Limited','Public Limited','Trust','Society','Individual')),
  pan TEXT NOT NULL CHECK (pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
  gstin TEXT, legal_name TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  firm_id UUID REFERENCES firms(id)
);
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id UUID NOT NULL REFERENCES firms(id), full_name TEXT NOT NULL, email TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('Partner','Manager','Executive','Reviewer','Client')),
  auth_user_id UUID
);
CREATE TABLE customers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES firms(id), client_id UUID NOT NULL REFERENCES clients(id), name TEXT NOT NULL
);
CREATE TABLE time_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL, user_id UUID NOT NULL, is_billable BOOLEAN NOT NULL DEFAULT true, hourly_rate_paise INTEGER
);
-- Financial tables carrying client_id (074 will add restrictive policies to these).
CREATE TABLE journal_entries (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID NOT NULL, client_id UUID, narration TEXT
);
CREATE TABLE sales_invoices (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID NOT NULL, client_id UUID, total_paise BIGINT
);

CREATE OR REPLACE FUNCTION get_my_firm_id() RETURNS UUID AS $$
  SELECT firm_id FROM users WHERE auth_user_id = auth.uid() LIMIT 1;
$$ LANGUAGE SQL SECURITY DEFINER STABLE;

-- Permissive firm-isolation policies (mirror the real schema) so the RESTRICTIVE
-- policies added by 074 are observable.
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON clients TO authenticated;
DROP POLICY IF EXISTS "clients_own_firm" ON clients;
CREATE POLICY "clients_own_firm" ON clients FOR ALL USING (firm_id = get_my_firm_id()) WITH CHECK (firm_id = get_my_firm_id());

ALTER TABLE journal_entries ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON journal_entries TO authenticated;
DROP POLICY IF EXISTS "je_own_firm" ON journal_entries;
CREATE POLICY "je_own_firm" ON journal_entries FOR ALL USING (firm_id = get_my_firm_id()) WITH CHECK (firm_id = get_my_firm_id());

ALTER TABLE sales_invoices ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON sales_invoices TO authenticated;
DROP POLICY IF EXISTS "si_own_firm" ON sales_invoices;
CREATE POLICY "si_own_firm" ON sales_invoices FOR ALL USING (firm_id = get_my_firm_id()) WITH CHECK (firm_id = get_my_firm_id());

\echo '--- applying 073 ---'
--__FWD_073__
\echo '--- applying 074 ---'
--__FWD_074__

-- Seed: firm A with external + internal clients, a partner + a staff member,
-- and one journal entry + one sales invoice for each client.
INSERT INTO firms(id,name,email) VALUES ('11111111-1111-1111-1111-111111111111','Firm A','a@x.com');
INSERT INTO users(firm_id,full_name,email,role,auth_user_id) VALUES
  ('11111111-1111-1111-1111-111111111111','PA','pa@a','Partner',  'a1a1a1a1-0000-0000-0000-000000000001'),
  ('11111111-1111-1111-1111-111111111111','SA','sa@a','Executive','a1a1a1a1-0000-0000-0000-000000000002');
INSERT INTO clients(id,client_name,entity_type,pan,legal_name,status,firm_id,is_internal) VALUES
  ('33333333-3333-3333-3333-333333333333','Ext Client A','Private Limited','AAAAA1111A','Ext Client A','active','11111111-1111-1111-1111-111111111111',false),
  ('44444444-4444-4444-4444-444444444444','Firm A Internal','Partnership','BBBBB2222B','Firm A Internal','active','11111111-1111-1111-1111-111111111111',true);
UPDATE firms SET internal_client_id='44444444-4444-4444-4444-444444444444' WHERE id='11111111-1111-1111-1111-111111111111';
INSERT INTO journal_entries(firm_id,client_id,narration) VALUES
  ('11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','external JE'),
  ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','internal JE');
INSERT INTO sales_invoices(firm_id,client_id,total_paise) VALUES
  ('11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333',100000),
  ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444',200000);

-- ── Staff (non-Partner): internal client + its financials are invisible (G1) ──
SELECT set_config('request.jwt.claim.sub','a1a1a1a1-0000-0000-0000-000000000002', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM clients) = 1, 'staff sees only the external client (internal hidden by RLS)';
  ASSERT (SELECT count(*) FROM clients WHERE is_internal) = 0, 'staff cannot see the internal client row';
  ASSERT (SELECT count(*) FROM journal_entries) = 1, 'staff sees only external client journals';
  ASSERT (SELECT count(*) FROM sales_invoices) = 1, 'staff sees only external client sales invoices';
  -- write to the internal client's books must be denied
  BEGIN
    INSERT INTO journal_entries(firm_id,client_id,narration)
      VALUES ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','illegal');
    RAISE EXCEPTION 'staff write to internal client journals should be DENIED';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  -- write to an external client's books must succeed
  INSERT INTO journal_entries(firm_id,client_id,narration)
    VALUES ('11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','legal staff JE');
  RAISE NOTICE 'PASS: staff blocked from internal client row + financials (read+write); external access intact';
END $$;
RESET ROLE;

-- ── Partner: full access to internal client + its financials ─────────────────
SELECT set_config('request.jwt.claim.sub','a1a1a1a1-0000-0000-0000-000000000001', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM clients) = 2, 'partner sees both clients incl. internal';
  ASSERT (SELECT count(*) FROM clients WHERE is_internal) = 1, 'partner sees the internal client';
  ASSERT (SELECT count(*) FROM journal_entries WHERE client_id='44444444-4444-4444-4444-444444444444') = 1, 'partner sees internal journals';
  ASSERT (SELECT count(*) FROM sales_invoices) = 2, 'partner sees all sales invoices';
  RAISE NOTICE 'PASS: partner retains full access to internal client + financials';
END $$;
RESET ROLE;

-- ── Rollback 074: G1 enforcement removed -> staff can see internal again ──────
\echo '--- applying 074 rollback ---'
--__RB_074__
DO $$ BEGIN
  ASSERT NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname='my_internal_client_id'), 'my_internal_client_id dropped';
  ASSERT (SELECT count(*) FROM pg_policies WHERE policyname='clients_internal_partner_only') = 0, 'clients restrictive policy dropped';
  ASSERT (SELECT count(*) FROM pg_policies WHERE policyname='journal_entries_internal_partner_only') = 0, 'JE restrictive policy dropped';
  RAISE NOTICE 'PASS: 074 rollback removed all restrictive policies + helper';
END $$;
SELECT set_config('request.jwt.claim.sub','a1a1a1a1-0000-0000-0000-000000000002', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM clients) = 2, 'after 074 rollback, firm-isolation alone lets staff see all firm clients (proves 074 enforced G1)';
  RAISE NOTICE 'PASS: 074 was the G1 enforcer (visibility restored on rollback)';
END $$;
RESET ROLE;

\echo '--- applying 073 rollback ---'
--__RB_073__

\echo '=== BATCH 2 RLS VERIFICATION: ALL ASSERTIONS PASSED ==='
