-- Batch 5 (Amendment v1.1) capture-layer DB harness (migration 078).
-- Run by tests/test_batch5_migration.py. Proves: capture columns present
-- (billable_rate_paise, cost_rate_paise from Batch 1; billed_invoice_id + the
-- GENERATED is_billed from 078); is_billed is system-controlled (derived from
-- billed_invoice_id; manual write rejected); unbilled query; clean rollback.
\set ON_ERROR_STOP on
\echo '=== BATCH 5 CAPTURE VERIFICATION START ==='

DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- Schema as it exists post-Batch-1 (billable_rate_paise / cost_rate_paise present).
CREATE TABLE users (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID, full_name TEXT,
  role TEXT, cost_rate_paise BIGINT
);
CREATE TABLE client_sales_invoices (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID);
CREATE TABLE time_entries (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID NOT NULL, user_id UUID NOT NULL,
  client_id UUID, task_id UUID, duration_minutes INTEGER,
  is_billable BOOLEAN NOT NULL DEFAULT true,
  hourly_rate_paise INTEGER, billable_rate_paise BIGINT
);

\echo '--- applying 078 ---'
--__FWD_078__

-- 1. Capture columns present
DO $$ BEGIN
  ASSERT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='time_entries' AND column_name='billable_rate_paise'), 'billable_rate_paise (Batch 1)';
  ASSERT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='cost_rate_paise'), 'cost_rate_paise (Batch 1)';
  ASSERT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='time_entries' AND column_name='billed_invoice_id'), 'billed_invoice_id (078)';
  ASSERT (SELECT is_generated FROM information_schema.columns WHERE table_name='time_entries' AND column_name='is_billed') = 'ALWAYS', 'is_billed is GENERATED';
  ASSERT EXISTS (SELECT 1 FROM information_schema.table_constraints WHERE constraint_name='time_entries_billed_invoice_id_fkey'), 'billed_invoice_id FK';
  ASSERT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='idx_time_entries_unbilled'), 'unbilled index';
  RAISE NOTICE 'PASS: capture columns + generated is_billed + index';
END $$;

-- 2. is_billed derives from billed_invoice_id (authoritative)
INSERT INTO client_sales_invoices(id, firm_id) VALUES ('aaaaaaaa-0000-0000-0000-000000000001','11111111-1111-1111-1111-111111111111');
INSERT INTO time_entries(firm_id,user_id,client_id,duration_minutes,is_billable,billable_rate_paise,billed_invoice_id) VALUES
  ('11111111-1111-1111-1111-111111111111','22222222-0000-0000-0000-000000000001','33333333-0000-0000-0000-000000000001',60,true,100000,NULL),                                   -- unbilled
  ('11111111-1111-1111-1111-111111111111','22222222-0000-0000-0000-000000000001','33333333-0000-0000-0000-000000000001',30,true,100000,'aaaaaaaa-0000-0000-0000-000000000001'); -- billed
DO $$ BEGIN
  ASSERT (SELECT is_billed FROM time_entries WHERE billed_invoice_id IS NULL) = false, 'NULL linkage -> not billed';
  ASSERT (SELECT is_billed FROM time_entries WHERE billed_invoice_id IS NOT NULL) = true, 'linkage set -> billed';
  RAISE NOTICE 'PASS: is_billed derives from billed_invoice_id';
END $$;

-- 3. is_billed is system-controlled: a manual write is rejected by Postgres.
DO $$ BEGIN
  BEGIN
    INSERT INTO time_entries(firm_id,user_id,is_billable,is_billed)
      VALUES ('11111111-1111-1111-1111-111111111111','22222222-0000-0000-0000-000000000002',true,true);
    RAISE EXCEPTION 'manual write to GENERATED is_billed should have been rejected';
  EXCEPTION WHEN generated_always THEN NULL;  -- expected: cannot insert into a generated column
  END;
  RAISE NOTICE 'PASS: is_billed cannot be set manually (system-controlled)';
END $$;

-- 4. Unbilled query (billable AND not billed)
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM time_entries WHERE is_billable AND billed_invoice_id IS NULL) = 1, 'one unbilled billable entry';
  RAISE NOTICE 'PASS: unbilled query';
END $$;

-- 5. Rollback 078
\echo '--- applying 078 rollback ---'
--__RB_078__
DO $$ BEGIN
  ASSERT NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='time_entries' AND column_name='is_billed'), 'is_billed dropped';
  ASSERT NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='time_entries' AND column_name='billed_invoice_id'), 'billed_invoice_id dropped';
  RAISE NOTICE 'PASS: 078 rollback clean';
END $$;

\echo '=== BATCH 5 CAPTURE VERIFICATION: ALL ASSERTIONS PASSED ==='
