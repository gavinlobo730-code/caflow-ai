-- Batch 3 (Amendment v1.1) billing DB-guarantee verification harness.
-- Run by tests/test_batch3_billing_migration.py (splices real 073/074/075 + 075 rollback).
-- Proves: duplicate-invoice safety (unique index), G3 single-link uniqueness,
-- restrictive G1 RLS on client_sales_invoices, and the collections lifecycle at
-- the data layer; then a clean 075 rollback.
\set ON_ERROR_STOP on
\echo '=== BATCH 3 BILLING VERIFICATION START ==='

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

CREATE TABLE firms (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), name TEXT NOT NULL, email TEXT NOT NULL);
CREATE TABLE clients (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  client_name TEXT NOT NULL,
  entity_type TEXT NOT NULL CHECK (entity_type IN ('Proprietorship','Partnership','LLP','Private Limited','Public Limited','Trust','Society','Individual')),
  pan TEXT NOT NULL CHECK (pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
  gstin TEXT, legal_name TEXT, state_code TEXT,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','inactive')),
  firm_id UUID REFERENCES firms(id)
);
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID NOT NULL REFERENCES firms(id),
  full_name TEXT NOT NULL, email TEXT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('Partner','Manager','Executive','Reviewer','Client')), auth_user_id UUID
);
CREATE TABLE customers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES firms(id), client_id UUID NOT NULL REFERENCES clients(id), name TEXT NOT NULL
);
CREATE TABLE time_entries (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), firm_id UUID NOT NULL, user_id UUID NOT NULL,
  is_billable BOOLEAN NOT NULL DEFAULT true, hourly_rate_paise INTEGER
);
-- existing sales-invoice table (faithful subset; 075 adds billing_* columns)
CREATE TABLE client_sales_invoices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL, client_id UUID, customer_id UUID,
  invoice_no TEXT, total_paise BIGINT NOT NULL DEFAULT 0,
  paid_paise BIGINT NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'draft'
);
CREATE TABLE client_sales_invoice_lines (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(), invoice_id UUID REFERENCES client_sales_invoices(id)
);
GRANT SELECT, INSERT, UPDATE, DELETE ON client_sales_invoices TO authenticated;

CREATE OR REPLACE FUNCTION get_my_firm_id() RETURNS UUID AS $$
  SELECT firm_id FROM users WHERE auth_user_id = auth.uid() LIMIT 1;
$$ LANGUAGE SQL SECURITY DEFINER STABLE;

\echo '--- applying 073 / 074 / 075 ---'
--__FWD_073__
--__FWD_074__
--__FWD_075__

-- Seed
INSERT INTO firms(id,name,email) VALUES ('11111111-1111-1111-1111-111111111111','Firm A','a@x.com');
INSERT INTO users(firm_id,full_name,email,role,auth_user_id) VALUES
  ('11111111-1111-1111-1111-111111111111','PA','pa@a','Partner',  'a1a1a1a1-0000-0000-0000-000000000001'),
  ('11111111-1111-1111-1111-111111111111','SA','sa@a','Executive','a1a1a1a1-0000-0000-0000-000000000002');
INSERT INTO clients(id,client_name,entity_type,pan,legal_name,status,firm_id,is_internal) VALUES
  ('33333333-3333-3333-3333-333333333333','Ext Client A','Private Limited','AAAAA1111A','Ext','active','11111111-1111-1111-1111-111111111111',false),
  ('44444444-4444-4444-4444-444444444444','Firm A Internal','Partnership','BBBBB2222B','Int','active','11111111-1111-1111-1111-111111111111',true);
UPDATE firms SET internal_client_id='44444444-4444-4444-4444-444444444444' WHERE id='11111111-1111-1111-1111-111111111111';
INSERT INTO customers(id,firm_id,client_id,name) VALUES ('66666666-6666-6666-6666-666666666666','11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','Ext A as customer');
INSERT INTO billing_schedules(id,firm_id,client_id,arrangement,cadence,amount_paise,gst_rate) VALUES
  ('77777777-7777-7777-7777-777777777777','11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','retainer','monthly',100000,18);
INSERT INTO client_firm_customer_links(firm_id,client_id,internal_customer_id) VALUES
  ('11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','66666666-6666-6666-6666-666666666666');

-- 1. DUPLICATE-INVOICE SAFETY (unique index on billing_schedule_id, billing_period)
DO $$ BEGIN
  INSERT INTO client_sales_invoices(firm_id,client_id,customer_id,total_paise,billing_schedule_id,billing_period,source)
    VALUES ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','66666666-6666-6666-6666-666666666666',118000,'77777777-7777-7777-7777-777777777777','2026-06','billing');
  BEGIN
    INSERT INTO client_sales_invoices(firm_id,client_id,customer_id,total_paise,billing_schedule_id,billing_period,source)
      VALUES ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','66666666-6666-6666-6666-666666666666',118000,'77777777-7777-7777-7777-777777777777','2026-06','billing');
    RAISE EXCEPTION 'duplicate (schedule, period) invoice should have been rejected';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
  -- a different period for the same schedule is allowed
  INSERT INTO client_sales_invoices(firm_id,client_id,customer_id,total_paise,billing_schedule_id,billing_period,source)
    VALUES ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','66666666-6666-6666-6666-666666666666',118000,'77777777-7777-7777-7777-777777777777','2026-07','billing');
  RAISE NOTICE 'PASS: duplicate-invoice safety (unique billing run)';
END $$;

-- 2. G3 single customer link per practice client
DO $$ BEGIN
  BEGIN
    INSERT INTO client_firm_customer_links(firm_id,client_id,internal_customer_id)
      VALUES ('11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','66666666-6666-6666-6666-666666666666');
    RAISE EXCEPTION 'duplicate customer link should have been rejected (G3)';
  EXCEPTION WHEN unique_violation THEN NULL;
  END;
  RAISE NOTICE 'PASS: G3 one-customer-link-per-practice-client';
END $$;

-- 3. Restrictive G1 RLS on client_sales_invoices (internal invoices hidden from staff)
SELECT set_config('request.jwt.claim.sub','a1a1a1a1-0000-0000-0000-000000000002', false);  -- staff
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM client_sales_invoices) = 0, 'staff must NOT see internal-client invoices';
END $$;
RESET ROLE;
-- add an external-client invoice, then re-check staff sees only that one
INSERT INTO client_sales_invoices(firm_id,client_id,customer_id,total_paise,status)
  VALUES ('11111111-1111-1111-1111-111111111111','33333333-3333-3333-3333-333333333333','66666666-6666-6666-6666-666666666666',50000,'issued');
SELECT set_config('request.jwt.claim.sub','a1a1a1a1-0000-0000-0000-000000000002', false);
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM client_sales_invoices) = 1, 'staff sees only the external-client invoice';
  RAISE NOTICE 'PASS: restrictive G1 RLS hides internal invoices from staff';
END $$;
RESET ROLE;
SELECT set_config('request.jwt.claim.sub','a1a1a1a1-0000-0000-0000-000000000001', false);  -- partner
SET ROLE authenticated;
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM client_sales_invoices) = 3, 'partner sees all invoices (2 internal + 1 external)';
  RAISE NOTICE 'PASS: partner sees internal + external invoices';
END $$;
RESET ROLE;

-- 4. Collections lifecycle at the data layer (raised -> partially_paid -> paid),
--    traceability preserved across transitions.
DO $$
DECLARE inv_id uuid;
BEGIN
  SELECT id INTO inv_id FROM client_sales_invoices
   WHERE billing_schedule_id='77777777-7777-7777-7777-777777777777' AND billing_period='2026-06';
  UPDATE client_sales_invoices SET paid_paise=50000,
    status = CASE WHEN 50000 >= total_paise THEN 'paid' ELSE 'partially_paid' END WHERE id=inv_id;
  ASSERT (SELECT status FROM client_sales_invoices WHERE id=inv_id) = 'partially_paid', 'partial receipt -> partially_paid';
  UPDATE client_sales_invoices SET paid_paise=118000,
    status = CASE WHEN 118000 >= total_paise THEN 'paid' ELSE 'partially_paid' END WHERE id=inv_id;
  ASSERT (SELECT status FROM client_sales_invoices WHERE id=inv_id) = 'paid', 'full receipt -> paid';
  ASSERT (SELECT billing_schedule_id FROM client_sales_invoices WHERE id=inv_id) = '77777777-7777-7777-7777-777777777777', 'traceability preserved';
  RAISE NOTICE 'PASS: collections lifecycle (raised -> partially_paid -> paid) with traceability';
END $$;

-- 5. Rollback 075
\echo '--- applying 075 rollback ---'
--__RB_075__
DO $$ BEGIN
  ASSERT NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='client_sales_invoices' AND column_name='billing_schedule_id'), 'billing_schedule_id dropped';
  ASSERT NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='uq_client_sales_invoices_billing_run'), 'unique index dropped';
  ASSERT (SELECT count(*) FROM pg_policies WHERE policyname='client_sales_invoices_internal_partner_only') = 0, 'restrictive policy dropped';
  ASSERT EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name='client_sales_invoices'), 'invoice table intact';
  RAISE NOTICE 'PASS: 075 rollback removed billing traceability + policies';
END $$;

\echo '=== BATCH 3 BILLING VERIFICATION: ALL ASSERTIONS PASSED ==='
