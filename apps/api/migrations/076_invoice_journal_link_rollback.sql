-- PracticeSync AI — Migration 076 ROLLBACK (Invoice→Journal link)
-- Drops only the objects added by 076. Idempotent.

DROP INDEX IF EXISTS idx_client_sales_invoices_unposted;
ALTER TABLE client_sales_invoices DROP CONSTRAINT IF EXISTS client_sales_invoices_journal_entry_id_fkey;
ALTER TABLE client_sales_invoices DROP COLUMN IF EXISTS journal_entry_id;
