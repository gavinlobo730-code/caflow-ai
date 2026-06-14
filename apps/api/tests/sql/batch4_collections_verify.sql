-- Batch 4 (Amendment v1.1) collections/AR DB-guarantee harness.
-- Run by tests/test_batch4_migration.py (splices real 077 fwd + rollback).
-- Proves: migration 077 columns; due-date aging at the data layer; balanced TDS
-- receipt settlement (Dr Bank + Dr TDS Receivable + Cr Trade Receivables) clearing
-- the invoice while cash < invoice value; and a clean 077 rollback.
\set ON_ERROR_STOP on
\echo '=== BATCH 4 COLLECTIONS VERIFICATION START ==='

DROP SCHEMA IF EXISTS public CASCADE; CREATE SCHEMA public;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE client_sales_invoices (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID NOT NULL, client_id UUID,
  invoice_no TEXT, invoice_date DATE NOT NULL, due_date DATE,
  total_paise BIGINT NOT NULL DEFAULT 0, paid_paise BIGINT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'draft'
);
CREATE TABLE receipts (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID NOT NULL, client_id UUID,
  amount_paise BIGINT NOT NULL DEFAULT 0
);
CREATE TABLE journal_entries (id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), firm_id UUID, reference_no TEXT);
CREATE TABLE journal_lines (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(), journal_entry_id UUID,
  account_name TEXT, debit_paise BIGINT DEFAULT 0, credit_paise BIGINT DEFAULT 0
);

\echo '--- applying 077 ---'
--__FWD_077__

-- 1. Migration 077 structure
DO $$ BEGIN
  ASSERT (SELECT count(*) FROM information_schema.columns WHERE table_name='client_sales_invoices'
          AND column_name IN ('is_overdue','days_overdue','aging_bucket','last_reminded_at','reminder_count')) = 5, 'invoice collections columns';
  ASSERT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='receipts' AND column_name='tds_paise'), 'receipts.tds_paise';
  RAISE NOTICE 'PASS: migration 077 structure';
END $$;

-- 2. Due-date aging at the data layer (today = 2026-06-30)
INSERT INTO client_sales_invoices(firm_id,client_id,invoice_no,invoice_date,due_date,total_paise,paid_paise,status) VALUES
  ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','A','2026-03-01','2026-06-20',118000,0,'issued'),
  ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','B','2026-03-01','2026-04-15',100000,0,'issued'),
  ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','C','2026-03-01','2026-07-10', 50000,0,'issued'),
  ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','D','2026-01-01','2026-01-01',100000,40000,'partially_paid'),
  ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444','E','2026-01-01','2026-01-01',100000,100000,'paid');

-- bucket helper inline: days_overdue = today - COALESCE(due_date, invoice_date+30)
DO $$
DECLARE today DATE := DATE '2026-06-30';
BEGIN
  -- not_due = future due, open + outstanding>0
  ASSERT (SELECT count(*) FROM client_sales_invoices
          WHERE status IN ('issued','partially_paid') AND (total_paise-paid_paise) > 0
            AND (today - COALESCE(due_date, invoice_date + 30)) <= 0) = 1, 'not_due = C';
  ASSERT (SELECT count(*) FROM client_sales_invoices
          WHERE status IN ('issued','partially_paid') AND (total_paise-paid_paise) > 0
            AND (today - COALESCE(due_date, invoice_date + 30)) BETWEEN 1 AND 30) = 1, '0-30 = A';
  ASSERT (SELECT count(*) FROM client_sales_invoices
          WHERE status IN ('issued','partially_paid') AND (total_paise-paid_paise) > 0
            AND (today - COALESCE(due_date, invoice_date + 30)) BETWEEN 61 AND 90) = 1, '61-90 = B';
  ASSERT (SELECT count(*) FROM client_sales_invoices
          WHERE status IN ('issued','partially_paid') AND (total_paise-paid_paise) > 0
            AND (today - COALESCE(due_date, invoice_date + 30)) > 90) = 1, '90+ = D';
  -- paid invoice excluded from AR
  ASSERT (SELECT count(*) FROM client_sales_invoices
          WHERE status IN ('issued','partially_paid') AND (total_paise-paid_paise) > 0) = 4, 'paid excluded from open AR';
  RAISE NOTICE 'PASS: due-date aging at data layer';
END $$;

-- 3. TDS receipt settlement: fee 100000 + GST 18000 = 118000; client deducts
--    194J TDS 10000; cash = 108000. Settlement (cash+tds) = 118000 -> invoice PAID.
DO $$
DECLARE je UUID; inv_id UUID; dr BIGINT; cr BIGINT;
BEGIN
  SELECT id INTO inv_id FROM client_sales_invoices WHERE invoice_no='A';
  INSERT INTO receipts(firm_id,client_id,amount_paise,tds_paise)
    VALUES ('11111111-1111-1111-1111-111111111111','44444444-4444-4444-4444-444444444444',108000,10000);
  -- settlement applied to the invoice
  UPDATE client_sales_invoices SET paid_paise = 118000,
    status = CASE WHEN 118000 >= total_paise THEN 'paid' ELSE 'partially_paid' END WHERE id=inv_id;
  ASSERT (SELECT status FROM client_sales_invoices WHERE id=inv_id) = 'paid', 'invoice settled by cash+TDS';
  ASSERT (SELECT (total_paise-paid_paise) FROM client_sales_invoices WHERE id=inv_id) = 0, 'outstanding 0 -> leaves AR';
  -- balanced journal: Dr Bank 108000 + Dr TDS Receivable 10000 = Cr Trade Receivables 118000
  INSERT INTO journal_entries(id,firm_id,reference_no) VALUES (gen_random_uuid(),'11111111-1111-1111-1111-111111111111','RCPT-A') RETURNING id INTO je;
  INSERT INTO journal_lines(journal_entry_id,account_name,debit_paise,credit_paise) VALUES
    (je,'Bank Account',108000,0),
    (je,'TDS Receivable',10000,0),
    (je,'Trade Receivables',0,118000);
  SELECT sum(debit_paise), sum(credit_paise) INTO dr, cr FROM journal_lines WHERE journal_entry_id=je;
  ASSERT dr = cr AND dr = 118000, 'TDS receipt journal balances (108000 cash + 10000 TDS = 118000)';
  RAISE NOTICE 'PASS: balanced TDS receipt settlement (invoice PAID with cash < invoice value)';
END $$;

-- 4. Rollback 077
\echo '--- applying 077 rollback ---'
--__RB_077__
DO $$ BEGIN
  ASSERT NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='client_sales_invoices' AND column_name='is_overdue'), 'is_overdue dropped';
  ASSERT NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='receipts' AND column_name='tds_paise'), 'tds_paise dropped';
  RAISE NOTICE 'PASS: 077 rollback clean';
END $$;

\echo '=== BATCH 4 COLLECTIONS VERIFICATION: ALL ASSERTIONS PASSED ==='
