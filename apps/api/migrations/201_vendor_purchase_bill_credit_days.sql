-- Port "Net 30"-style payment terms from Customers/Sales Invoices to
-- Vendors/Purchase Bills.
--
-- VendorIn/VendorUpdateIn (models/parties.py) already declare a credit_days
-- field and it already flows straight through model_dump() into every
-- insert/update in routers/vendors.py — the column itself was simply never
-- created. Same class of bug as migrations 199/200 (model ahead of schema):
-- the moment any caller actually sent credit_days, the insert/update would
-- have errored against PostgREST's schema cache.
ALTER TABLE public.vendors
  ADD COLUMN IF NOT EXISTS credit_days INTEGER NOT NULL DEFAULT 30;

-- Snapshot the effective credit terms onto each purchase bill, mirroring
-- migration 134 (client_sales_invoices.credit_days): the vendor's
-- credit_days is a DEFAULT, not a permanent rule, so a later edit to the
-- vendor's terms must not silently move the due date of an already-created
-- bill. Nullable — pre-existing bills keep NULL here.
ALTER TABLE public.purchase_bills
  ADD COLUMN IF NOT EXISTS credit_days INTEGER;
