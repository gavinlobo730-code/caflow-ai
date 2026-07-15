-- Migration 206 — mandatory Product/Service link on auto-generated invoice
-- sources (recurring invoice templates + firm billing/retainer schedules).
--
-- Manual documents (Sales Invoices, Purchase Bills, Credit/Debit Notes) already
-- require service_catalogue_id on every line (migration 184 + the InvoiceLineIn/
-- PurchaseBillLineIn model_validator). The two auto-generation paths below build
-- the exact same InvoiceLineIn under the hood, so they must carry the same link
-- or generation crashes at run time instead of failing fast at template/schedule
-- creation. Both tables are empty in production (verified before writing this
-- migration), so these are immediate NOT NULL constraints — no backfill path
-- needed.

ALTER TABLE public.recurring_invoice_template_lines
    ADD COLUMN service_catalogue_id UUID NOT NULL REFERENCES public.service_catalogue(id);

-- billing_schedules.service_id was added in migration 073 as a nullable,
-- FK-less "bridge" column, before service_catalogue existed (migration 176).
-- It's real now: tighten it to match.
ALTER TABLE public.billing_schedules
    ALTER COLUMN service_id SET NOT NULL;

ALTER TABLE public.billing_schedules
    ADD CONSTRAINT billing_schedules_service_id_fkey
    FOREIGN KEY (service_id) REFERENCES public.service_catalogue(id);
