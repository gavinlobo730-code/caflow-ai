-- PracticeSync AI — Migration 100: client_sales_invoices soft-delete
--
-- Adds deleted_at for soft-deletion of DRAFT invoices only. A draft is not a
-- legal document (no journal, not reported in GSTR-1), so a CA may discard it.
-- Soft-delete (not a hard DELETE) keeps the row for the audit trail — every
-- deletion is also written to audit_log. Issued/partially-paid/paid/cancelled
-- invoices can never be deleted (enforced in the application layer).
--
-- Additive, idempotent, backward-compatible. No financial data is changed.
-- Drafts are never included in any accounting report, so filtering them out has
-- zero effect on Trial Balance / P&L / Balance Sheet.

ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ;

COMMENT ON COLUMN client_sales_invoices.deleted_at IS
  'Soft-delete marker. Set only when a DRAFT invoice is discarded by the CA. '
  'NULL for all live invoices. Issued/paid/cancelled invoices are never deleted.';

-- Partial index so the common "live invoices" listing stays fast as the table
-- accumulates discarded drafts.
CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_not_deleted
  ON client_sales_invoices (client_id, invoice_date DESC)
  WHERE deleted_at IS NULL;
