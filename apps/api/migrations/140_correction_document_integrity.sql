-- Migration 140: correction-document integrity (Production Readiness Phase 1).
--
-- Supports the three accounting-integrity corrections:
--   C1 Credit-note application  — a credit note reduces the linked invoice's
--      receivable in the sub-ledger (not just the GL), so sub-ledger, GL AR control
--      and the customer statement reconcile.
--   C2 Sales-invoice cancellation / C3 Purchase-bill cancellation — reversal-based
--      (append-only) cancellation; these need no new columns (both docs already
--      carry journal_entry_id), so this migration is only the credit-note pieces.
--
-- All additive with safe defaults → behaviour-inert on existing rows; constant
-- DEFAULTs are metadata-only on PostgreSQL 17 (no table rewrite).

-- (C1) Sub-ledger: portion of an invoice settled by credit notes, distinct from
-- paid_paise (cash/TDS via receipts). Invoice net outstanding = total - paid - credited.
ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS credited_paise BIGINT NOT NULL DEFAULT 0;

-- (C1) Portion of a credit note that has been applied against invoices.
ALTER TABLE public.credit_notes
  ADD COLUMN IF NOT EXISTS applied_paise BIGINT NOT NULL DEFAULT 0;

-- (C1) Credit-note -> invoice application records (mirrors receipt_allocations), so
-- every reduction of an invoice's receivable by a credit note is a first-class,
-- auditable row. CASCADE from the credit note; the invoice is never hard-deleted
-- once issued, so the invoice FK is plain (RESTRICT by default).
CREATE TABLE IF NOT EXISTS public.credit_note_allocations (
  id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id          UUID NOT NULL,
  credit_note_id   UUID NOT NULL REFERENCES public.credit_notes(id) ON DELETE CASCADE,
  sales_invoice_id UUID NOT NULL REFERENCES public.client_sales_invoices(id),
  allocated_paise  BIGINT NOT NULL CHECK (allocated_paise > 0),
  created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (credit_note_id, sales_invoice_id)
);
CREATE INDEX IF NOT EXISTS idx_cna_credit_note ON public.credit_note_allocations (credit_note_id);
CREATE INDEX IF NOT EXISTS idx_cna_invoice     ON public.credit_note_allocations (sales_invoice_id);
CREATE INDEX IF NOT EXISTS idx_cna_firm        ON public.credit_note_allocations (firm_id);
