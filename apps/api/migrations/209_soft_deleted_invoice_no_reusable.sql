-- Migration 209 — a soft-deleted sales invoice's number must be reusable.
--
-- client_sales_invoices.invoice_no is CA-typed (Task: "Remove hardcoded
-- sales-invoice numbering, add manual invoice_no field + validation") and
-- enforced unique per client via UNIQUE(firm_id, client_id, invoice_no)
-- (migration 151). Migration 100 later added deleted_at (soft delete for
-- draft invoices) — but the uniqueness constraint was never revisited, so a
-- deleted draft's invoice_no stayed permanently blocked even though the
-- invoice is invisible everywhere in the UI. Bug report: a CA created a
-- draft "00002", deleted it within the same minute, and every later attempt
-- to use "00002" for a real invoice failed with "Invoice number '00002'
-- already exists for this client" — a number the app shows nowhere as taken.
--
-- Fix: replace the plain UNIQUE constraint with a PARTIAL unique index that
-- only applies to live rows (deleted_at IS NULL). The app-level pre-check
-- (_assert_invoice_no_available, routers/sales_invoices.py) is updated in
-- the same change to filter deleted_at too, so this index is purely the
-- backstop for a genuine concurrent race, matching how every other
-- uniqueness check in this codebase pairs an app-level check with a DB
-- constraint of the same shape.
--
-- Idempotent: drops the constraint only if it still exists in its old form,
-- creates the partial index only if absent.

DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'client_sales_invoices_firm_client_invoice_no_key'
  ) THEN
    ALTER TABLE public.client_sales_invoices
      DROP CONSTRAINT client_sales_invoices_firm_client_invoice_no_key;
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS client_sales_invoices_firm_client_invoice_no_live_key
  ON public.client_sales_invoices (firm_id, client_id, invoice_no)
  WHERE deleted_at IS NULL;
