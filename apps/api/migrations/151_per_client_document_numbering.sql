-- 151 — Per-client document numbering (fixes audit finding F6).
--
-- Problem
-- -------
-- client_sales_invoices and credit_notes generate their document number with a
-- sequence scoped per (firm_id, client_id, financial_year) —
--   routers/sales_invoices.py:_next_invoice_seq  ->  SINV-{fy}-{seq}
--   routers/credit_notes.py:_next_cn_seq          ->  CN-{fy}-{seq}
-- but the UNIQUE constraint from migration 050 was scoped per (firm_id, number)
-- only. So the SECOND bookkeeping client of a firm computes SINV-{fy}-0001
-- (its own count is 0), which collides with the FIRST client's SINV-{fy}-0001;
-- the graceful-retry in services/numbering.py recomputes the same client-scoped
-- sequence and collides on every attempt, then 500s. Net effect: only one client
-- per firm could ever issue invoices — a launch blocker for any multi-client firm.
--
-- Fix
-- ---
-- Each client is a distinct supplier business and must keep its OWN continuous
-- invoice/credit-note series (CGST Rule 46 — the serial number must be unique
-- for the supplier within a financial year, NOT across unrelated suppliers the
-- firm happens to keep books for). So the numbering-per-client is correct and the
-- UNIQUE key is what must widen: (firm_id, number) -> (firm_id, client_id, number).
--
-- Safety: widening a unique key (adding a column) only RELAXES uniqueness, so it
-- can never conflict with existing rows; and because the bug prevented a second
-- client from ever inserting, no colliding data exists to migrate. Idempotent:
-- drops any unique constraint whose column set is exactly the old one, and adds
-- the new one only if absent — safe to re-run.

-- ── client_sales_invoices: (firm_id, invoice_no) -> (firm_id, client_id, invoice_no)
DO $$
DECLARE con record;
BEGIN
  FOR con IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'public.client_sales_invoices'::regclass
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname::text ORDER BY a.attname::text)
        FROM unnest(c.conkey) AS k(attnum)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
      ) = ARRAY['firm_id', 'invoice_no']
  LOOP
    EXECUTE format('ALTER TABLE public.client_sales_invoices DROP CONSTRAINT %I', con.conname);
  END LOOP;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint c
    WHERE c.conrelid = 'public.client_sales_invoices'::regclass
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname::text ORDER BY a.attname::text)
        FROM unnest(c.conkey) AS k(attnum)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
      ) = ARRAY['client_id', 'firm_id', 'invoice_no']
  ) THEN
    ALTER TABLE public.client_sales_invoices
      ADD CONSTRAINT client_sales_invoices_firm_client_invoice_no_key
      UNIQUE (firm_id, client_id, invoice_no);
  END IF;
END $$;

-- ── credit_notes: (firm_id, credit_note_no) -> (firm_id, client_id, credit_note_no)
DO $$
DECLARE con record;
BEGIN
  FOR con IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'public.credit_notes'::regclass
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname::text ORDER BY a.attname::text)
        FROM unnest(c.conkey) AS k(attnum)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
      ) = ARRAY['credit_note_no', 'firm_id']
  LOOP
    EXECUTE format('ALTER TABLE public.credit_notes DROP CONSTRAINT %I', con.conname);
  END LOOP;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint c
    WHERE c.conrelid = 'public.credit_notes'::regclass
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname::text ORDER BY a.attname::text)
        FROM unnest(c.conkey) AS k(attnum)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
      ) = ARRAY['client_id', 'credit_note_no', 'firm_id']
  ) THEN
    ALTER TABLE public.credit_notes
      ADD CONSTRAINT credit_notes_firm_client_credit_note_no_key
      UNIQUE (firm_id, client_id, credit_note_no);
  END IF;
END $$;
