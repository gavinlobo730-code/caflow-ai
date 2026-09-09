-- 350 — sales_debit_notes and purchase_credit_notes are numbered per client, so
--       their UNIQUE key must be per client too.
--
-- Problem
-- -------
-- Migration 151 fixed exactly this for client_sales_invoices and credit_notes,
-- and migration 159 for debit_notes and receipts: the number is computed per
-- (firm_id, client_id, financial year) while the UNIQUE constraint covered
-- (firm_id, number) only, so the firm's SECOND client computed 0001 — its own
-- series is empty — and the database rejected it. services/numbering.py's
-- retry recomputes the same client-scoped sequence, so all six attempts
-- collide and the request 500s. Only one client per firm could ever raise the
-- document.
--
-- Migration 210 then CREATED sales_debit_notes and purchase_credit_notes with
-- the old per-firm key, and routers/sales_debit_notes.py::_next_sdn_seq and
-- routers/purchase_credit_notes.py::_next_pcn_seq number per client. So the
-- same launch blocker has been live on those two document types since 210:
--
--     client A raises SDN-2627-0001   -> inserted
--     client B raises its first one   -> computes 0001, UNIQUE (firm_id,
--                                        debit_note_no) rejects it, six
--                                        identical retries, 500.
--
-- Fix
-- ---
-- Widen the key, exactly as 151 argued: each client is a distinct business
-- keeping its own continuous series (CGST Rule 46 — the serial number is
-- unique for the SUPPLIER within a financial year, not across unrelated
-- suppliers whose books one firm happens to keep). A debit note raised on a
-- sale and a credit note raised on a purchase are both documents of the
-- CLIENT, not of the practice.
--
-- Safety: adding a column to a unique key only RELAXES uniqueness, so it can
-- never conflict with existing rows. Idempotent — drops a unique constraint
-- only when its column set is exactly the old one, and adds the new one only
-- when absent.
--
-- Companion change, no migration: services/numbering.py::next_sequence now
-- reads the MAXIMUM number in the series rather than COUNTING the rows, and
-- refuses a scope that is not the one NUMBER_SERIES records for the table.

-- ── sales_debit_notes: (firm_id, debit_note_no) -> (firm_id, client_id, debit_note_no)
DO $$
DECLARE con record;
BEGIN
  FOR con IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'public.sales_debit_notes'::regclass
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname::text ORDER BY a.attname::text)
        FROM unnest(c.conkey) AS k(attnum)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
      ) = ARRAY['debit_note_no', 'firm_id']
  LOOP
    EXECUTE format('ALTER TABLE public.sales_debit_notes DROP CONSTRAINT %I', con.conname);
  END LOOP;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint c
    WHERE c.conrelid = 'public.sales_debit_notes'::regclass
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname::text ORDER BY a.attname::text)
        FROM unnest(c.conkey) AS k(attnum)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
      ) = ARRAY['client_id', 'debit_note_no', 'firm_id']
  ) THEN
    ALTER TABLE public.sales_debit_notes
      ADD CONSTRAINT sales_debit_notes_firm_client_debit_note_no_key
      UNIQUE (firm_id, client_id, debit_note_no);
  END IF;
END $$;

-- ── purchase_credit_notes: (firm_id, credit_note_no) -> (firm_id, client_id, credit_note_no)
DO $$
DECLARE con record;
BEGIN
  FOR con IN
    SELECT c.conname
    FROM pg_constraint c
    WHERE c.conrelid = 'public.purchase_credit_notes'::regclass
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname::text ORDER BY a.attname::text)
        FROM unnest(c.conkey) AS k(attnum)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
      ) = ARRAY['credit_note_no', 'firm_id']
  LOOP
    EXECUTE format('ALTER TABLE public.purchase_credit_notes DROP CONSTRAINT %I', con.conname);
  END LOOP;

  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint c
    WHERE c.conrelid = 'public.purchase_credit_notes'::regclass
      AND c.contype = 'u'
      AND (
        SELECT array_agg(a.attname::text ORDER BY a.attname::text)
        FROM unnest(c.conkey) AS k(attnum)
        JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = k.attnum
      ) = ARRAY['client_id', 'credit_note_no', 'firm_id']
  ) THEN
    ALTER TABLE public.purchase_credit_notes
      ADD CONSTRAINT purchase_credit_notes_firm_client_credit_note_no_key
      UNIQUE (firm_id, client_id, credit_note_no);
  END IF;
END $$;
