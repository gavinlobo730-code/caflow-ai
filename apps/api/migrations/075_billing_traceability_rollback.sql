-- PracticeSync AI — Migration 075 ROLLBACK (Billing Traceability & Idempotency)
-- Drops only the objects added by 075. Idempotent. Existing invoices untouched
-- (the dropped columns are nullable additions).

DROP POLICY IF EXISTS "client_sales_invoices_internal_partner_only" ON client_sales_invoices;
DROP POLICY IF EXISTS "client_sales_invoices_own_firm" ON client_sales_invoices;

DROP INDEX IF EXISTS uq_client_sales_invoices_billing_run;
DROP INDEX IF EXISTS idx_client_sales_invoices_billing_schedule;

ALTER TABLE client_sales_invoices DROP CONSTRAINT IF EXISTS client_sales_invoices_billing_schedule_id_fkey;
ALTER TABLE client_sales_invoices DROP COLUMN IF EXISTS source;
ALTER TABLE client_sales_invoices DROP COLUMN IF EXISTS billing_period;
ALTER TABLE client_sales_invoices DROP COLUMN IF EXISTS billing_schedule_id;
