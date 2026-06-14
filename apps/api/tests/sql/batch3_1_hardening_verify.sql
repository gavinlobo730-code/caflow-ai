-- Batch 3.1 hardening verification harness (migration 076 + CoA resolution).
-- Run by tests/test_batch3_1_migration.py. Proves: 076 adds the invoice→journal
-- link (column + FK + partial index for issued-but-unposted detection); the
-- seeded firm-wide CoA resolves for the internal client via the exact
-- _find_account query pattern; and a clean 076 rollback.
\set ON_ERROR_STOP on
\echo '=== BATCH 3.1 HARDENING VERIFICATION START ==='

DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE firms (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), name TEXT NOT NULL);
CREATE TABLE journal_entries (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID, client_id UUID,
  reference_no TEXT, entry_date DATE
);
CREATE TABLE chart_of_accounts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id UUID NOT NULL, client_id UUID,
  account_code TEXT, account_name TEXT, account_type TEXT, account_subtype TEXT,
  is_active BOOLEAN NOT NULL DEFAULT true
);
CREATE TABLE client_sales_invoices (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id UUID NOT NULL, client_id UUID, total_paise BIGINT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft'
);

\echo '--- applying 076 ---'
--__FWD_076__

-- Seed firm-wide master CoA (client_id NULL) with names matching the posting
-- engine patterns (mirror of services/coa_seed_service.STANDARD_COA essentials).
INSERT INTO chart_of_accounts(firm_id, client_id, account_code, account_name, account_type, is_active) VALUES
  ('11111111-1111-1111-1111-111111111111', NULL, '1201', 'Trade Receivables',      'Asset',     true),
  ('11111111-1111-1111-1111-111111111111', NULL, '1101', 'Bank Account',           'Asset',     true),
  ('11111111-1111-1111-1111-111111111111', NULL, '2002', 'GST Output Tax Payable', 'Liability', true),
  ('11111111-1111-1111-1111-111111111111', NULL, '4001', 'Sales Revenue',          'Income',    true);

-- 1. Migration 076 structural checks
DO $$ BEGIN
  ASSERT EXISTS (SELECT 1 FROM information_schema.columns
                 WHERE table_name='client_sales_invoices' AND column_name='journal_entry_id'), 'journal_entry_id column';
  ASSERT EXISTS (SELECT 1 FROM information_schema.table_constraints
                 WHERE constraint_name='client_sales_invoices_journal_entry_id_fkey'), 'journal_entry_id FK';
  ASSERT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='idx_client_sales_invoices_unposted'), 'unposted partial index';
  RAISE NOTICE 'PASS: migration 076 structure';
END $$;

-- 2. Posting succeeds with seeded CoA — the internal client resolves accounts via
--    the exact _find_account predicate (firm match AND (client_id=X OR client_id IS NULL)
--    AND account_name ILIKE pattern AND is_active).
DO $$
DECLARE internal_id uuid := '44444444-4444-4444-4444-444444444444';
BEGIN
  ASSERT (SELECT count(*) FROM chart_of_accounts
          WHERE firm_id='11111111-1111-1111-1111-111111111111'
            AND (client_id = internal_id OR client_id IS NULL)
            AND account_name ILIKE '%Trade Receivable%' AND is_active) >= 1, 'Trade Receivables resolves';
  ASSERT (SELECT count(*) FROM chart_of_accounts
          WHERE firm_id='11111111-1111-1111-1111-111111111111'
            AND (client_id = internal_id OR client_id IS NULL)
            AND account_name ILIKE '%Sales%' AND is_active) >= 1, 'Sales resolves';
  ASSERT (SELECT count(*) FROM chart_of_accounts
          WHERE firm_id='11111111-1111-1111-1111-111111111111'
            AND (client_id = internal_id OR client_id IS NULL)
            AND account_name ILIKE '%GST Output%' AND is_active) >= 1, 'GST Output resolves';
  ASSERT (SELECT count(*) FROM chart_of_accounts
          WHERE firm_id='11111111-1111-1111-1111-111111111111'
            AND (client_id = internal_id OR client_id IS NULL)
            AND account_name ILIKE '%Bank%' AND is_active) >= 1, 'Bank resolves';
  RAISE NOTICE 'PASS: seeded firm CoA resolves for the internal client (posting can succeed)';
END $$;

-- 3. Detection: an issued invoice with NULL journal_entry_id is "unposted".
INSERT INTO journal_entries(id, firm_id) VALUES ('99999999-9999-9999-9999-999999999999','11111111-1111-1111-1111-111111111111');
INSERT INTO client_sales_invoices(firm_id, client_id, total_paise, status, journal_entry_id) VALUES
  ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444',118000,'issued','99999999-9999-9999-9999-999999999999'),  -- posted
  ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444',118000,'issued',NULL);                                   -- unposted
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM client_sales_invoices WHERE status='issued' AND journal_entry_id IS NULL) = 1, 'one issued-but-unposted detected';
  RAISE NOTICE 'PASS: issued-but-unposted detection';
END $$;

-- 4. Rollback 076
\echo '--- applying 076 rollback ---'
--__RB_076__
DO $$ BEGIN
  ASSERT NOT EXISTS (SELECT 1 FROM information_schema.columns
                     WHERE table_name='client_sales_invoices' AND column_name='journal_entry_id'), 'journal_entry_id dropped';
  ASSERT NOT EXISTS (SELECT 1 FROM pg_indexes WHERE indexname='idx_client_sales_invoices_unposted'), 'unposted index dropped';
  RAISE NOTICE 'PASS: 076 rollback clean';
END $$;

\echo '=== BATCH 3.1 HARDENING VERIFICATION: ALL ASSERTIONS PASSED ==='
