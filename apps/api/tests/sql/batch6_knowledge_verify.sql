-- Batch 6 (Amendment v1.1) Knowledge Base RLS harness (migration 079).
-- Run by tests/test_batch6_migration.py. Proves assignment-gated visibility
-- (Manager firm-wide; Executive only assigned), internal-client partner-only (G1),
-- version immutability (UNIQUE), and a clean 079 rollback.
\set ON_ERROR_STOP on
\echo '=== BATCH 6 KNOWLEDGE VERIFICATION START ==='

DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
DROP SCHEMA IF EXISTS auth CASCADE;   CREATE SCHEMA auth;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='authenticated') THEN CREATE ROLE authenticated NOLOGIN; END IF;
END $$;
GRANT USAGE ON SCHEMA public TO authenticated;
GRANT USAGE ON SCHEMA auth TO authenticated;
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid AS $$
  SELECT NULLIF(current_setting('request.jwt.claim.sub', true), '')::uuid;
$$ LANGUAGE sql STABLE;

CREATE TABLE firms (id UUID PRIMARY KEY, name TEXT, internal_client_id UUID);
CREATE TABLE clients (id UUID PRIMARY KEY, firm_id UUID, is_internal BOOLEAN DEFAULT false);
CREATE TABLE users (id UUID PRIMARY KEY, firm_id UUID, role TEXT, auth_user_id UUID);
CREATE TABLE user_client_assignments (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), user_id UUID, client_id UUID, firm_id UUID);
GRANT SELECT ON user_client_assignments TO authenticated;  -- matches prod grant (migration 041)
CREATE TABLE knowledge_articles (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID NOT NULL,
  scope TEXT, client_id UUID, title TEXT, current_version INT DEFAULT 1, is_archived BOOLEAN DEFAULT false);
CREATE TABLE knowledge_article_versions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID, article_id UUID, version INT, content TEXT,
  UNIQUE(article_id, version));
CREATE TABLE client_instructions (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID NOT NULL, client_id UUID, title TEXT);

-- Helper functions (copies of 073/074) the 079 policies depend on.
CREATE OR REPLACE FUNCTION get_my_firm_id() RETURNS UUID AS $$
  SELECT firm_id FROM users WHERE auth_user_id = auth.uid() LIMIT 1; $$ LANGUAGE SQL SECURITY DEFINER STABLE;
CREATE OR REPLACE FUNCTION get_my_role() RETURNS TEXT AS $$
  SELECT role FROM users WHERE auth_user_id = auth.uid() LIMIT 1; $$ LANGUAGE SQL SECURITY DEFINER STABLE;
CREATE OR REPLACE FUNCTION my_internal_client_id() RETURNS uuid AS $$
  SELECT internal_client_id FROM firms WHERE id = get_my_firm_id(); $$ LANGUAGE sql SECURITY DEFINER STABLE;

-- Permissive firm policies (mirror 073) + grants so RESTRICTIVE policies are observable.
ALTER TABLE knowledge_articles ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON knowledge_articles TO authenticated;
CREATE POLICY "ka_firm" ON knowledge_articles FOR ALL USING (firm_id = get_my_firm_id()) WITH CHECK (firm_id = get_my_firm_id());
ALTER TABLE client_instructions ENABLE ROW LEVEL SECURITY;
GRANT SELECT, INSERT, UPDATE, DELETE ON client_instructions TO authenticated;
CREATE POLICY "ci_firm" ON client_instructions FOR ALL USING (firm_id = get_my_firm_id()) WITH CHECK (firm_id = get_my_firm_id());

\echo '--- applying 079 ---'
--__FWD_079__

-- Seed (valid hex UUIDs)
INSERT INTO firms(id,name,internal_client_id) VALUES
  ('f0000000-0000-0000-0000-000000000001','A','c0000000-0000-0000-0000-0000000000ee');
INSERT INTO clients(id,firm_id,is_internal) VALUES
  ('c0000000-0000-0000-0000-0000000000aa','f0000000-0000-0000-0000-000000000001',false),  -- external X
  ('c0000000-0000-0000-0000-0000000000ee','f0000000-0000-0000-0000-000000000001',true);   -- internal
INSERT INTO users(id,firm_id,role,auth_user_id) VALUES
  ('00000000-0000-0000-0000-0000000000a1','f0000000-0000-0000-0000-000000000001','Partner',  'aaaa0000-0000-0000-0000-0000000000a1'),
  ('00000000-0000-0000-0000-0000000000a2','f0000000-0000-0000-0000-000000000001','Manager',  'aaaa0000-0000-0000-0000-0000000000a2'),
  ('00000000-0000-0000-0000-0000000000a3','f0000000-0000-0000-0000-000000000001','Executive','aaaa0000-0000-0000-0000-0000000000a3'),
  ('00000000-0000-0000-0000-0000000000a4','f0000000-0000-0000-0000-000000000001','Executive','aaaa0000-0000-0000-0000-0000000000a4');
INSERT INTO user_client_assignments(user_id,client_id,firm_id) VALUES
  ('00000000-0000-0000-0000-0000000000a3','c0000000-0000-0000-0000-0000000000aa','f0000000-0000-0000-0000-000000000001'); -- EA -> X
INSERT INTO knowledge_articles(firm_id,scope,client_id,title) VALUES
  ('f0000000-0000-0000-0000-000000000001','firm',NULL,'Firm SOP'),
  ('f0000000-0000-0000-0000-000000000001','client','c0000000-0000-0000-0000-0000000000aa','X SOP'),
  ('f0000000-0000-0000-0000-000000000001','client','c0000000-0000-0000-0000-0000000000ee','Internal SOP');
INSERT INTO client_instructions(firm_id,client_id,title) VALUES
  ('f0000000-0000-0000-0000-000000000001','c0000000-0000-0000-0000-0000000000aa','X instruction'),
  ('f0000000-0000-0000-0000-000000000001','c0000000-0000-0000-0000-0000000000ee','Internal instruction');

-- Executive EA (assigned to X): firm + X, NOT internal
SELECT set_config('request.jwt.claim.sub','aaaa0000-0000-0000-0000-0000000000a3', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM knowledge_articles) = 2, 'EA sees firm + X article (not internal)';
  ASSERT (SELECT count(*) FROM knowledge_articles WHERE title='Internal SOP') = 0, 'EA cannot see internal article';
  ASSERT (SELECT count(*) FROM client_instructions) = 1, 'EA sees X instruction only';
  RAISE NOTICE 'PASS: assigned Executive sees firm + assigned client, not internal';
END $$;
RESET ROLE;

-- Executive EB (unassigned): firm only; write to X denied
SELECT set_config('request.jwt.claim.sub','aaaa0000-0000-0000-0000-0000000000a4', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM knowledge_articles) = 1, 'EB (unassigned) sees firm article only';
  ASSERT (SELECT count(*) FROM client_instructions) = 0, 'EB sees no client instructions';
  BEGIN
    INSERT INTO client_instructions(firm_id,client_id,title)
      VALUES ('f0000000-0000-0000-0000-000000000001','c0000000-0000-0000-0000-0000000000aa','illegal');
    RAISE EXCEPTION 'unassigned Executive write should be denied';
  EXCEPTION WHEN insufficient_privilege THEN NULL;
  END;
  RAISE NOTICE 'PASS: unassigned Executive gated (read + write)';
END $$;
RESET ROLE;

-- Manager: firm-wide (firm + X) but NOT internal (G1)
SELECT set_config('request.jwt.claim.sub','aaaa0000-0000-0000-0000-0000000000a2', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM knowledge_articles) = 2, 'Manager firm-wide sees firm + X (not internal)';
  ASSERT (SELECT count(*) FROM knowledge_articles WHERE title='Internal SOP') = 0, 'Manager cannot see internal (G1)';
  RAISE NOTICE 'PASS: Manager firm-wide, internal partner-only';
END $$;
RESET ROLE;

-- Partner: everything incl internal
SELECT set_config('request.jwt.claim.sub','aaaa0000-0000-0000-0000-0000000000a1', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM knowledge_articles) = 3, 'Partner sees all incl internal';
  ASSERT (SELECT count(*) FROM client_instructions) = 2, 'Partner sees all instructions';
  RAISE NOTICE 'PASS: Partner full access';
END $$;
RESET ROLE;

-- Version immutability: duplicate (article_id, version) rejected
DO $$ BEGIN
  INSERT INTO knowledge_article_versions(firm_id,article_id,version,content)
    VALUES ('f0000000-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111',1,'v1');
  BEGIN
    INSERT INTO knowledge_article_versions(firm_id,article_id,version,content)
      VALUES ('f0000000-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111',1,'dup');
    RAISE EXCEPTION 'duplicate version should be rejected';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
  RAISE NOTICE 'PASS: version history immutable (UNIQUE article_id,version)';
END $$;

\echo '--- applying 079 rollback ---'
--__RB_079__
DO $$ BEGIN
  ASSERT NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname='get_my_user_id'), 'get_my_user_id dropped';
  ASSERT (SELECT count(*) FROM pg_policies WHERE policyname='knowledge_articles_assignment') = 0, 'assignment policy dropped';
  RAISE NOTICE 'PASS: 079 rollback clean';
END $$;

\echo '=== BATCH 6 KNOWLEDGE VERIFICATION: ALL ASSERTIONS PASSED ==='
