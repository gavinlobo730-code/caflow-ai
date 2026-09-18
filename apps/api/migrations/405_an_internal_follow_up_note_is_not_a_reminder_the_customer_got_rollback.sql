-- Rollback for 405.
--
-- Dropping the two columns is clean; what it CANNOT undo is step 3's repair,
-- because the pre-405 reminder_count conflated two different events and the
-- repair is what told them apart. Re-applying 405 after this rollback is
-- harmless: the back-fill is derived from invoice_deliveries and is idempotent,
-- so it recomputes the same answer. What is lost is the internal count, which
-- the next nightly sweep rebuilds from zero.
DROP INDEX IF EXISTS public.idx_client_sales_invoices_internal_followup;

ALTER TABLE public.client_sales_invoices DROP COLUMN IF EXISTS internal_followup_count;
ALTER TABLE public.client_sales_invoices DROP COLUMN IF EXISTS last_internal_followup_at;

COMMENT ON COLUMN public.client_sales_invoices.reminder_count   IS NULL;
COMMENT ON COLUMN public.client_sales_invoices.last_reminded_at IS NULL;
