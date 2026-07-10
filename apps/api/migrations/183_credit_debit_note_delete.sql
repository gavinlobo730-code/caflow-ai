-- 183 — Soft-delete support for Credit Notes and Debit Notes.
--
-- Neither table had a deleted_at column, so there was no way to delete a
-- mistakenly-created DRAFT credit/debit note at all (only issue existed).
-- Mirrors client_sales_invoices' soft-delete (migration 100): a DELETE
-- endpoint sets deleted_at rather than removing the row, so the delete is
-- reversible in principle and never touches an issued/applied document —
-- those are legal records (CGST Act §34) with a posted journal once issued.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS is a no-op on re-run.

ALTER TABLE public.credit_notes ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;
ALTER TABLE public.debit_notes  ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

-- Partial indexes so "list active rows" (the common case) stays fast.
CREATE INDEX IF NOT EXISTS idx_credit_notes_active
  ON public.credit_notes (firm_id, client_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_debit_notes_active
  ON public.debit_notes (firm_id, client_id) WHERE deleted_at IS NULL;
