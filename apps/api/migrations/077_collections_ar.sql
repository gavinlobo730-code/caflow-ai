-- PracticeSync AI — Migration 077: Collections & AR (Batch 4)
-- Amendment v1.1 (Phase 10B) — Revenue Operations collections.
--
-- Additive, backward-compatible, idempotent. Money stays integer paise.
--
-- Per the approved design:
--  * Overdue is DERIVED + denormalised (no status mutation). Payment status
--    (draft/issued/partially_paid/paid/cancelled) is preserved; collections
--    metadata is maintained by a daily sweep.
--  * Aging is DUE-DATE based; due_date else invoice_date + credit_days.
--  * TDS deducted by clients on firm fees is captured on the existing receipt
--    (tds_paise) — settlement value = amount_paise + tds_paise.

-- 1. Collections metadata on the sales invoice (derived; non-destructive)
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS is_overdue       boolean NOT NULL DEFAULT false;
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS days_overdue     integer NOT NULL DEFAULT 0;
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS aging_bucket     text;            -- not_due | 0-30 | 31-60 | 61-90 | 90+
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS last_reminded_at timestamptz;
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS reminder_count   integer NOT NULL DEFAULT 0;

COMMENT ON COLUMN client_sales_invoices.is_overdue IS
  'Batch 4: derived (due_date < today AND outstanding > 0). Payment status is never mutated to overdue.';
COMMENT ON COLUMN client_sales_invoices.aging_bucket IS
  'Batch 4 (due-date based): not_due | 0-30 | 31-60 | 61-90 | 90+.';

-- 2. TDS deducted by the client on the firm's fees, captured on the receipt.
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS tds_paise bigint NOT NULL DEFAULT 0;
COMMENT ON COLUMN receipts.tds_paise IS
  'Batch 4: TDS deducted by the client on the firm fee (IT Act §194J). Settlement = amount_paise + tds_paise. Posts Dr TDS Receivable.';

-- 3. Index for the overdue sweep + dashboard (firm-scoped, open receivables only).
CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_open
  ON client_sales_invoices(firm_id, due_date)
  WHERE status IN ('issued','partially_paid');
CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_overdue_flag
  ON client_sales_invoices(firm_id) WHERE is_overdue;
