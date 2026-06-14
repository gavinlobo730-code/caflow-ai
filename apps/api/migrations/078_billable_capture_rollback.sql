-- PracticeSync AI — Migration 078 ROLLBACK (Billable / billed capture)
-- Drops only the objects added by 078. Idempotent. Drops the generated column
-- before its source column.

DROP INDEX IF EXISTS idx_time_entries_unbilled;
ALTER TABLE time_entries DROP COLUMN IF EXISTS is_billed;
ALTER TABLE time_entries DROP CONSTRAINT IF EXISTS time_entries_billed_invoice_id_fkey;
ALTER TABLE time_entries DROP COLUMN IF EXISTS billed_invoice_id;
