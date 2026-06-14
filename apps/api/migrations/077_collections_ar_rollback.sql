-- PracticeSync AI — Migration 077 ROLLBACK (Collections & AR)
-- Drops only the objects added by 077. Idempotent.

DROP INDEX IF EXISTS idx_client_sales_invoices_open;
DROP INDEX IF EXISTS idx_client_sales_invoices_overdue_flag;

ALTER TABLE receipts DROP COLUMN IF EXISTS tds_paise;

ALTER TABLE client_sales_invoices DROP COLUMN IF EXISTS reminder_count;
ALTER TABLE client_sales_invoices DROP COLUMN IF EXISTS last_reminded_at;
ALTER TABLE client_sales_invoices DROP COLUMN IF EXISTS aging_bucket;
ALTER TABLE client_sales_invoices DROP COLUMN IF EXISTS days_overdue;
ALTER TABLE client_sales_invoices DROP COLUMN IF EXISTS is_overdue;
