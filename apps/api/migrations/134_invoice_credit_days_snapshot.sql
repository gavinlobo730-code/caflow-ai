-- Migration 134: snapshot credit terms onto each sales invoice.
--
-- Credit Days on a customer is a DEFAULT, not a permanent rule. When an invoice
-- is created we resolve its effective credit terms (explicit due_date > explicit
-- credit_days override > customer.credit_days default) and store BOTH the due_date
-- (already present) and the credit_days used, ON THE INVOICE. That snapshot makes
-- each invoice self-contained: later edits to the customer's Credit Days never
-- change existing invoices' due dates or terms.
--
-- Nullable: pre-existing invoices keep NULL here; collections already derives
-- their reference date from due_date (or invoice_date + fallback), so they are
-- unaffected.

ALTER TABLE public.client_sales_invoices
    ADD COLUMN IF NOT EXISTS credit_days INTEGER;
