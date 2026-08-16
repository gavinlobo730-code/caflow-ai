-- Migration 268: give a sales invoice the three facts GSTR-1 classifies it by.
--
-- domain/gst/classifier.py already routes a supply to the right GSTR-1 table —
-- NIL_EXEMPT, EXP_WP/EXP_WOP, B2B, B2CL, B2CS — citing CGST §23, §16(1)(a),
-- §16(3), §37 and Rule 59(2). It is complete and correct.
--
-- It just never receives the truth. gst_return_service builds its input from
-- client_sales_invoices, which carries none of the three columns the classifier
-- branches on, so every read falls back to a default:
--
--     supply_type       column absent -> r.get(...) or "taxable"  -> ALWAYS taxable
--     invoice_type      not read at all, hardcoded                -> ALWAYS Regular
--     is_reverse_charge column absent -> bool(r.get(..., False))  -> ALWAYS false
--
-- The consequences are filing errors, not cosmetic ones:
--
--   * a nil-rated, exempt or non-GST supply is declared as TAXABLE, in the wrong
--     table, inflating outward taxable turnover
--   * an SEZ supply or a deemed export is declared as an ordinary B2B invoice
--     rather than in the zero-rated tables — the recipient's refund claim under
--     CGST §16(3) has nothing to match against
--   * a reverse-charge supply is not flagged, so the return says the supplier
--     owes tax the recipient is actually liable for
--
-- Only one export path works today, by accident: the classifier also treats
-- place_of_supply '96' (other territory / export) as an export, and that column
-- does exist. Everything else defaults to a plain domestic taxable sale.
--
-- The allowed values deliberately match migration 036's identical CHECK
-- constraints on public.transactions. Two tables describing the same tax
-- concept with different vocabularies is how a classifier ends up needing a
-- translation layer, and there is no reason to invent one here.

ALTER TABLE public.client_sales_invoices
  -- CGST §23 / GSTR-1 table 8: nil-rated, exempted and non-GST outward supplies
  -- are declared separately from taxable ones.
  ADD COLUMN IF NOT EXISTS supply_type TEXT NOT NULL DEFAULT 'taxable'
      CHECK (supply_type IN ('taxable', 'zero_rated', 'nil_rated', 'exempt', 'non_gst')),
  -- CGST §16(1)(a) and §16(3): zero-rated supplies to an SEZ, and deemed
  -- exports, are declared with payment of IGST or under LUT/bond.
  ADD COLUMN IF NOT EXISTS invoice_type TEXT NOT NULL DEFAULT 'Regular'
      CHECK (invoice_type IN ('Regular', 'SEZ_with_payment', 'SEZ_without_payment', 'Deemed_export')),
  -- CGST §9(3)/(4): where the recipient is liable, the invoice carries the flag
  -- and GSTR-1 reports it so the two returns agree about who pays.
  ADD COLUMN IF NOT EXISTS is_reverse_charge BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.client_sales_invoices.supply_type IS
    'taxable | zero_rated | nil_rated | exempt | non_gst. Read by '
    'domain/gst/classifier.py to route the invoice to its GSTR-1 table.';
COMMENT ON COLUMN public.client_sales_invoices.invoice_type IS
    'Regular | SEZ_with_payment | SEZ_without_payment | Deemed_export (CGST §16(3)).';
COMMENT ON COLUMN public.client_sales_invoices.is_reverse_charge IS
    'True when the RECIPIENT is liable for the tax (CGST §9(3)/(4)).';

-- No backfill. Every existing invoice is a plain domestic taxable sale unless
-- somebody says otherwise, and the defaults say exactly that — which is also
-- what the code assumed before this migration, so nothing changes meaning for
-- data already recorded. Guessing retrospectively at which past invoices were
-- SEZ or exempt would put figures into a tax return that no one entered.
