-- Migration 270: give a recurring invoice template the same three GSTR-1 facts
-- migration 268 gave a sales invoice.
--
-- WHY THIS IS THE WORSE HALF OF THE SAME BUG
-- Migration 268 added supply_type / invoice_type / is_reverse_charge to
-- client_sales_invoices because defaulting them mis-declares a return. Task
-- #156 put controls on the invoice form; task #157 carried them through the CSV
-- import. Recurring templates were the remaining hole, and they are the one
-- that hurts most:
--
--     services/recurring_invoice_service.py builds its SalesInvoiceIn from the
--     template, and had no classification to copy — so every generated invoice
--     took the column defaults and went out as a plain domestic taxable sale.
--
-- The CSV importer at least has a CA watching the upload. This path runs
-- UNATTENDED, as job #6 of the daily sweep at 06:00 IST. A client on a
-- recurring SEZ engagement or an exempt service accumulates one mis-declared
-- invoice per period, every period, with nobody present to notice — and each
-- one lands in GSTR-1 as ordinary taxable B2B turnover.
--
-- WHY THE TEMPLATE AND NOT THE OCCURRENCE
-- The classification is a property of the engagement, not of the month: an SEZ
-- retainer is an SEZ supply in April and again in May. Storing it on the
-- template means the CA states it once, and every future occurrence inherits
-- it. A one-off correction still happens on the generated draft, which is
-- editable until issued.
--
-- The allowed values and defaults deliberately match migration 268 exactly
-- (which in turn matches migration 036's CHECKs on public.transactions). A
-- template that could hold a value an invoice cannot would fail at generation
-- time, in an unattended job, which is the worst place to discover it.

ALTER TABLE public.recurring_invoice_templates
  ADD COLUMN IF NOT EXISTS supply_type TEXT NOT NULL DEFAULT 'taxable'
      CHECK (supply_type IN ('taxable', 'zero_rated', 'nil_rated', 'exempt', 'non_gst'));

ALTER TABLE public.recurring_invoice_templates
  ADD COLUMN IF NOT EXISTS invoice_type TEXT NOT NULL DEFAULT 'Regular'
      CHECK (invoice_type IN ('Regular', 'SEZ_with_payment', 'SEZ_without_payment', 'Deemed_export'));

ALTER TABLE public.recurring_invoice_templates
  ADD COLUMN IF NOT EXISTS is_reverse_charge BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.recurring_invoice_templates.supply_type IS
  'GSTR-1 classification stamped on every invoice this template generates. CGST §23 / GSTR-1 table 8. Matches client_sales_invoices.supply_type (migration 268).';
COMMENT ON COLUMN public.recurring_invoice_templates.invoice_type IS
  'GSTR-1 classification stamped on every invoice this template generates. CGST §16(1)(a)/§16(3) zero-rated routes. Matches client_sales_invoices.invoice_type (migration 268).';
COMMENT ON COLUMN public.recurring_invoice_templates.is_reverse_charge IS
  'GSTR-1 classification stamped on every invoice this template generates. CGST §9(3)/§9(4). Matches client_sales_invoices.is_reverse_charge (migration 268).';

-- Existing templates keep the behaviour they already had: the defaults are
-- exactly what every generated invoice was implicitly getting before this
-- migration, so nothing that is running today changes meaning. A CA who needs a
-- different classification now has somewhere to say so.
