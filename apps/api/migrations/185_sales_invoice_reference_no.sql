-- Migration 185: add the missing reference_no column on client_sales_invoices.
--
-- SalesInvoiceIn/SalesInvoiceUpdateIn (apps/api/models/invoices.py) have
-- declared reference_no since the Blueprint's "Reference" field was wired
-- into the invoice editor (visual QA audit fix), and routers/sales_invoices.py
-- has always included it in the create/update payload sent to
-- client_sales_invoices — but no migration ever added the column itself.
-- Any invoice save with a non-empty Reference field fails against
-- PostgREST's schema cache ("column does not exist"), caught by the
-- router's generic exception handler and surfaced only as "Unable to
-- create invoice. Please try again." with no indication why.
--
-- TEXT, nullable, no default — matches the sibling reference_no columns on
-- receipts and purchase_payments (migration 050). Free-text PO/reference
-- number; never searched/filtered on, so no index.

ALTER TABLE client_sales_invoices
  ADD COLUMN IF NOT EXISTS reference_no TEXT;
