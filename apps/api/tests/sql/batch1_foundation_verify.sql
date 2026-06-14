-- Batch 1 (Amendment v1.1) migration verification harness.
-- Run by tests/test_batch1_foundation_migration.py, which splices the REAL
-- migration files into the --__FORWARD__ / --__ROLLBACK__ markers below.
-- Builds a faithful Supabase shim (auth.uid(), authenticated/anon/service_role
-- roles) + the real prerequisite tables, applies 073 twice (idempotency),
-- asserts structure/RLS/view/provisioning, then rolls back and re-asserts.
\set ON_ERROR_STOP on
\echo '=== BATCH 1 VERIFICATION START ==='

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

-- Prerequisite REAL tables (faithful subset of migrations 001/003/005/049/064)
CREATE TABLE firms (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  name TEXT NOT NULL, email TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE clients (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  client_name TEXT NOT NULL,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('Proprietorship','Partnership','LLP','Private Limited','Public Limited','Trust','Society','Individual')),
  pan TEXT NOT NULL CHECK (pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
  gstin TEXT, legal_name TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  firm_id UUID REFERENCES firms(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id UUID NOT NULL REFERENCES firms(id),
  full_name TEXT NOT NULL, email TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('Partner','Manager','Executive','Reviewer','Client')),
  auth_user_id UUID,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE customers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES firms(id),
  client_id UUID NOT NULL REFERENCES clients(id),
  name TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE TABLE time_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL, user_id UUID NOT NULL,
  is_billable BOOLEAN NOT NULL DEFAULT true,
  hourly_rate_paise INTEGER,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE OR REPLACE FUNCTION get_my_firm_id() RETURNS UUID AS $$
  SELECT firm_id FROM users WHERE auth_user_id = auth.uid() LIMIT 1;
$$ LANGUAGE SQL SECURITY DEFINER STABLE;

ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON clients TO authenticated;
GRANT SELECT ON clients TO anon;
DROP POLICY IF EXISTS "clients_own_firm" ON clients;
CREATE POLICY "clients_own_firm" ON clients
  FOR ALL USING (firm_id = get_my_firm_id()) WITH CHECK (firm_id = get_my_firm_id());

\echo '--- applying 073 (first time) ---'
--__FORWARD__
\echo '--- applying 073 (second time — must be idempotent) ---'
--__FORWARD__

INSERT INTO firms(id,name,email) VALUES
  ('11111111-1111-1111-1111-111111111111','Firm A','a@x.com'),
  ('22222222-2222-2222-2222-222222222222','Firm B','b@x.com');
INSERT INTO users(firm_id,full_name,email,role,auth_user_id) VALUES
  ('11111111-1111-1111-1111-111111111111','PA','pa@a','Partner',  'a1a1a1a1-0000-0000-0000-000000000001'),
  ('11111111-1111-1111-1111-111111111111','SA','sa@a','Executive','a1a1a1a1-0000-0000-0000-000000000002'),
  ('22222222-2222-2222-2222-222222222222','PB','pb@b','Partner',  'a2a2a2a2-0000-0000-0000-000000000001');
INSERT INTO clients(id,client_name,entity_type,pan,legal_name,status,firm_id,is_internal) VALUES
  ('33333333-3333-3333-3333-333333333333','Ext Client A','Private Limited','AAAAA1111A','Ext Client A','active','11111111-1111-1111-1111-111111111111',false),
  ('44444444-4444-4444-4444-444444444444','Firm A Internal','Partnership','BBBBB2222B','Firm A Internal','active','11111111-1111-1111-1111-111111111111',true),
  ('55555555-5555-5555-5555-555555555555','Client B','LLP','CCCCC3333C','Client B','active','22222222-2222-2222-2222-222222222222',false);
INSERT INTO customers(id,firm_id,client_id,name) VALUES
  ('66666666-6666-6666-6666-666666666666','11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','Ext A as customer');
INSERT INTO billing_schedules(firm_id,client_id,arrangement,cadence,amount_paise) VALUES
  ('11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','retainer','monthly',1000000);
INSERT INTO knowledge_articles(firm_id,scope,title) VALUES
  ('11111111-1111-1111-1111-111111111111','firm','SOP A'),
  ('22222222-2222-2222-2222-222222222222','firm','SOP B');

DO $$ BEGIN
  ASSERT (SELECT data_type FROM information_schema.columns WHERE table_name='clients' AND column_name='is_internal')='boolean', 'is_internal type';
  ASSERT (SELECT is_nullable FROM information_schema.columns WHERE table_name='clients' AND column_name='is_internal')='NO', 'is_internal NOT NULL';
  ASSERT (SELECT column_default FROM information_schema.columns WHERE table_name='clients' AND column_name='is_internal') LIKE 'false%', 'is_internal default false';
  ASSERT (SELECT data_type FROM information_schema.columns WHERE table_name='users' AND column_name='cost_rate_paise')='bigint', 'cost_rate_paise bigint';
  ASSERT (SELECT data_type FROM information_schema.columns WHERE table_name='time_entries' AND column_name='billable_rate_paise')='bigint', 'billable_rate_paise bigint';
  ASSERT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='firms' AND column_name='internal_client_id'), 'firms.internal_client_id';
  ASSERT (SELECT count(*) FROM information_schema.tables WHERE table_name IN
     ('billing_schedules','client_firm_customer_links','knowledge_articles','knowledge_article_versions','client_instructions'))=5, 'new tables';
  ASSERT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name='firms_internal_client_id_fkey'), 'FK firms.internal_client_id';
  ASSERT EXISTS (SELECT 1 FROM pg_constraint WHERE conname LIKE '%client_firm_customer_links%' AND contype='u'), 'UNIQUE(firm_id,client_id) on cfcl';
  ASSERT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='idx_billing_schedules_firm_next_run'), 'partial idx billing';
  ASSERT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='idx_knowledge_articles_title_fts'), 'GIN fts idx';
  ASSERT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='idx_knowledge_articles_tags'), 'GIN tags idx';
  ASSERT (SELECT relrowsecurity FROM pg_class WHERE relname='billing_schedules'), 'RLS billing_schedules';
  ASSERT (SELECT relrowsecurity FROM pg_class WHERE relname='client_instructions'), 'RLS client_instructions';
  ASSERT (SELECT count(*) FROM pg_policies WHERE tablename='billing_schedules' AND policyname='billing_schedules_partner_only')=1, 'policy billing partner-only';
  ASSERT (SELECT count(*) FROM pg_policies WHERE tablename='knowledge_articles' AND policyname='knowledge_articles_own_firm')=1, 'policy KB firm';
  ASSERT EXISTS (SELECT 1 FROM information_schema.views WHERE table_name='clients_external'), 'view clients_external';
  ASSERT EXISTS (SELECT 1 FROM pg_proc WHERE proname='provision_internal_client'), 'fn provision_internal_client';
  ASSERT EXISTS (SELECT 1 FROM pg_proc WHERE proname='get_my_role'), 'fn get_my_role';
  RAISE NOTICE 'PASS: structural assertions';
END $$;

DO $$ DECLARE v boolean; BEGIN
  INSERT INTO clients(client_name,entity_type,pan,legal_name,firm_id)
    VALUES ('Defaults Test','Individual','ZZZZZ9999Z','Defaults Test','11111111-1111-1111-1111-111111111111');
  SELECT is_internal INTO v FROM clients WHERE client_name='Defaults Test';
  ASSERT v = false, 'existing-style insert must default is_internal=false';
  DELETE FROM clients WHERE client_name='Defaults Test';
  RAISE NOTICE 'PASS: default-preservation';
END $$;

DO $$ BEGIN
  ASSERT (SELECT count(*) FROM clients_external WHERE id='44444444-4444-4444-4444-444444444444')=0, 'internal excluded from clients_external';
  ASSERT (SELECT count(*) FROM clients_external WHERE id='33333333-3333-3333-3333-333333333333')=1, 'external present in clients_external';
  RAISE NOTICE 'PASS: clients_external exclusion (superuser)';
END $$;

SELECT set_config('request.jwt.claim.sub','a1a1a1a1-0000-0000-0000-000000000002', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM billing_schedules)=0, 'staff must NOT see billing_schedules';
  BEGIN
    INSERT INTO billing_schedules(firm_id,client_id,arrangement,cadence)
      VALUES ('11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','retainer','monthly');
    RAISE EXCEPTION 'staff insert into billing_schedules should have been DENIED';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RAISE NOTICE 'PASS: staff blocked from billing_schedules (read+write)';
END $$;
RESET ROLE;

SELECT set_config('request.jwt.claim.sub','a1a1a1a1-0000-0000-0000-000000000001', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM billing_schedules)=1, 'partner must see firm billing_schedules';
  RAISE NOTICE 'PASS: partner can read billing_schedules';
END $$;
RESET ROLE;

SELECT set_config('request.jwt.claim.sub','a1a1a1a1-0000-0000-0000-000000000001', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM knowledge_articles)=1, 'firm A sees only its KB';
  ASSERT (SELECT count(*) FROM knowledge_articles WHERE title='SOP B')=0, 'firm A must NOT see firm B KB';
  RAISE NOTICE 'PASS: KB firm isolation (partner)';
END $$;
RESET ROLE;

SELECT set_config('request.jwt.claim.sub','a1a1a1a1-0000-0000-0000-000000000002', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM knowledge_articles)=1, 'firm A staff sees firm KB (not partner-gated)';
  RAISE NOTICE 'PASS: KB visible to staff (firm-scoped)';
END $$;
RESET ROLE;

SELECT set_config('request.jwt.claim.sub','a1a1a1a1-0000-0000-0000-000000000001', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM clients)=2, 'firm A raw clients = 2 (external + internal)';
  ASSERT (SELECT count(*) FROM clients_external)=1, 'firm A external population = 1 (G2 excludes internal + other firm)';
  RAISE NOTICE 'PASS: G2 exclusion under firm RLS';
END $$;
RESET ROLE;

INSERT INTO firms(id,name,email) VALUES ('99999999-9999-9999-9999-999999999999','Firm C','c@x.com');
DO $$ DECLARE id1 uuid; id2 uuid; linked uuid; BEGIN
  id1 := provision_internal_client('99999999-9999-9999-9999-999999999999','Firm C Internal','Partnership','DDDDD4444D',NULL);
  id2 := provision_internal_client('99999999-9999-9999-9999-999999999999','Firm C Internal','Partnership','DDDDD4444D',NULL);
  ASSERT id1 = id2, 'provision_internal_client must be idempotent';
  SELECT internal_client_id INTO linked FROM firms WHERE id='99999999-9999-9999-9999-999999999999';
  ASSERT linked = id1, 'firms.internal_client_id linked';
  ASSERT (SELECT is_internal FROM clients WHERE id=id1)=true, 'provisioned client is_internal=true';
  ASSERT (SELECT count(*) FROM clients WHERE firm_id='99999999-9999-9999-9999-999999999999' AND is_internal)=1, 'exactly one internal client';
  RAISE NOTICE 'PASS: provisioning idempotency';
END $$;

\echo '--- applying 073 rollback ---'
--__ROLLBACK__

DO $$ BEGIN
  ASSERT NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='clients' AND column_name='is_internal'), 'is_internal dropped';
  ASSERT NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='firms' AND column_name='internal_client_id'), 'internal_client_id dropped';
  ASSERT NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='cost_rate_paise'), 'cost_rate_paise dropped';
  ASSERT NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='time_entries' AND column_name='billable_rate_paise'), 'billable_rate_paise dropped';
  ASSERT (SELECT count(*) FROM information_schema.tables WHERE table_name IN
     ('billing_schedules','client_firm_customer_links','knowledge_articles','knowledge_article_versions','client_instructions'))=0, 'new tables dropped';
  ASSERT NOT EXISTS (SELECT 1 FROM information_schema.views WHERE table_name='clients_external'), 'view dropped';
  ASSERT NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname='provision_internal_client'), 'provision fn dropped';
  ASSERT NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname='get_my_role'), 'get_my_role dropped';
  ASSERT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='clients'), 'clients table intact';
  ASSERT (SELECT count(*) FROM clients) >= 3, 'client rows intact after rollback';
  ASSERT (SELECT count(*) FROM firms) >= 3, 'firm rows intact after rollback';
  RAISE NOTICE 'PASS: rollback restores pre-073 schema, data intact';
END $$;

\echo '=== BATCH 1 VERIFICATION: ALL ASSERTIONS PASSED ==='
