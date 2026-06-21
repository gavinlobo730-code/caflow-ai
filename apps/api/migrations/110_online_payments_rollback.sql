-- Rollback for 110_online_payments.sql
-- Restores the invoice_deliveries.kind CHECK to its prior (097/106) value and
-- drops the three payment tables. Safe only if no rows reference them.

ALTER TABLE public.invoice_deliveries DROP CONSTRAINT IF EXISTS invoice_deliveries_kind_check;
ALTER TABLE public.invoice_deliveries
    ADD CONSTRAINT invoice_deliveries_kind_check
    CHECK (kind IN ('invoice', 'reminder'));

DROP TABLE IF EXISTS public.customer_payment_events CASCADE;
DROP TABLE IF EXISTS public.customer_payments       CASCADE;
DROP TABLE IF EXISTS public.customer_payment_links  CASCADE;
