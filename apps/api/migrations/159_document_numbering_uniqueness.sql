-- 159 — Document-number uniqueness for debit notes, receipts, purchase
-- payments (R2.9; surfaced by the R1.1/F6 regression review, tracked as a
-- deliberately-separate follow-up because it is a different defect class:
-- MISSING uniqueness rather than a too-narrow key, so adding the constraint
-- needs a data de-dup step first, unlike 151's safe "widen an existing key").
--
-- Problem
-- -------
-- routers/debit_notes.py::_next_dn_seq and services/receipt_service.py::
-- _next_receipt_seq both compute a per-(firm_id, client_id, FY) sequence
-- (CGST Rule 46/53 — each client is its own supplier series), while
-- routers/purchase_payments.py::_next_payment_seq computes a per-(firm_id, FY)
-- sequence (a firm-wide payment voucher series — there is no statutory
-- per-vendor numbering requirement for payment vouchers). None of the three
-- backing tables (migrations 050, 145) has ANY uniqueness constraint on its
-- number column, so:
--   * a genuine concurrent race can commit two rows with the identical number
--     (CGST Act §34/Rule 53 requires debit notes to carry a unique serial —
--     this is a live statutory-compliance gap, not just a UX one);
--   * services/numbering.py's insert_with_number retry (already used by
--     debit_notes) can never fire — there is nothing for a duplicate insert
--     to violate, so it always "succeeds" first try even on a collision;
--   * receipts/purchase_payments do not even call insert_with_number today —
--     they insert the number directly with no retry at all.
--
-- Fix
-- ---
-- 1. De-dup FIRST (see below) — required because, unlike 151, this is adding
--    a constraint from nothing, so any duplicate already committed under the
--    unenforced gap would otherwise block the ALTER TABLE outright.
-- 2. Add the constraints matching each table's actual generator scope:
--      debit_notes:       UNIQUE (firm_id, client_id, debit_note_no)
--      receipts:           UNIQUE (firm_id, client_id, receipt_no)
--      purchase_payments:  UNIQUE (firm_id, payment_no)              -- per-firm, not per-client
--
-- De-dup approach
-- ---------------
-- A duplicate document number is real financial/statutory data — the
-- underlying row (money movement, journal link, allocations) must never be
-- deleted or silently altered. For any group of rows that would collide,
-- every row EXCEPT the earliest-created one (created_at, then id, as a
-- deterministic tie-break) gets its number suffixed with '-DUPn' so the
-- constraint can be added losslessly, and a NOTICE is raised naming the
-- table/row so a human can review whether that document needs a proper
-- statutory renumbering. This is expected to be a no-op on every database
-- that predates this migration in production use — the bug it repairs
-- allowed duplicates but nothing has generated one yet in practice.
DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT id, rn
    FROM (
      SELECT id,
             row_number() OVER (
               PARTITION BY firm_id, client_id, debit_note_no
               ORDER BY created_at ASC, id ASC
             ) AS rn
      FROM public.debit_notes
      WHERE debit_note_no IS NOT NULL
    ) x
    WHERE x.rn > 1
  LOOP
    RAISE NOTICE 'migration 159: renumbering duplicate debit_notes.id=% (occurrence #%) — review for correct statutory numbering', r.id, r.rn;
    UPDATE public.debit_notes SET debit_note_no = debit_note_no || '-DUP' || r.rn WHERE id = r.id;
  END LOOP;
END $$;

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT id, rn
    FROM (
      SELECT id,
             row_number() OVER (
               PARTITION BY firm_id, client_id, receipt_no
               ORDER BY created_at ASC, id ASC
             ) AS rn
      FROM public.receipts
      WHERE receipt_no IS NOT NULL
    ) x
    WHERE x.rn > 1
  LOOP
    RAISE NOTICE 'migration 159: renumbering duplicate receipts.id=% (occurrence #%) — review for correct statutory numbering', r.id, r.rn;
    UPDATE public.receipts SET receipt_no = receipt_no || '-DUP' || r.rn WHERE id = r.id;
  END LOOP;
END $$;

DO $$
DECLARE r record;
BEGIN
  FOR r IN
    SELECT id, rn
    FROM (
      SELECT id,
             row_number() OVER (
               PARTITION BY firm_id, payment_no
               ORDER BY created_at ASC, id ASC
             ) AS rn
      FROM public.purchase_payments
      WHERE payment_no IS NOT NULL
    ) x
    WHERE x.rn > 1
  LOOP
    RAISE NOTICE 'migration 159: renumbering duplicate purchase_payments.id=% (occurrence #%) — review for correct statutory numbering', r.id, r.rn;
    UPDATE public.purchase_payments SET payment_no = payment_no || '-DUP' || r.rn WHERE id = r.id;
  END LOOP;
END $$;

-- ── Constraints (additive-only; guarded so this file can be re-run safely) ──

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'debit_notes_firm_client_debit_note_no_key'
  ) THEN
    ALTER TABLE public.debit_notes
      ADD CONSTRAINT debit_notes_firm_client_debit_note_no_key
      UNIQUE (firm_id, client_id, debit_note_no);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'receipts_firm_client_receipt_no_key'
  ) THEN
    ALTER TABLE public.receipts
      ADD CONSTRAINT receipts_firm_client_receipt_no_key
      UNIQUE (firm_id, client_id, receipt_no);
  END IF;
END $$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'purchase_payments_firm_payment_no_key'
  ) THEN
    ALTER TABLE public.purchase_payments
      ADD CONSTRAINT purchase_payments_firm_payment_no_key
      UNIQUE (firm_id, payment_no);
  END IF;
END $$;
