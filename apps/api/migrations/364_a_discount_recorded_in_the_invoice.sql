-- Migration 364: a discount recorded in the invoice (CGST Act §15(3)(a)).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING (SALES-11)
-- ═══════════════════════════════════════════════════════════════════════════
-- There was no discount concept anywhere on the sales-invoice path — no
-- Pydantic field, no column, no editor control — and the taxable value was
-- `quantity × rate` with nothing subtracted. A trading client giving a 5% trade
-- discount could only have it netted into the rate by hand, which loses the
-- disclosure the customer's own copy shows and makes the invoice impossible to
-- reconcile against the client's price list.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE SECTION, AND THE ONE IT IS NOT
-- ═══════════════════════════════════════════════════════════════════════════
-- CGST §15(3): "The value of the supply shall not include any discount which is
-- given — (a) before or at the time of the supply if such discount has been
-- DULY RECORDED IN THE INVOICE issued in respect of such supply".
--
-- So a discount on the face of the invoice is excluded from the value of supply
-- — the tax is charged on the NET. That is what these columns are for, and
-- "duly recorded in the invoice" is why the discount is a column of its own
-- rather than a smaller rate: the statutory relief is conditional on the
-- invoice SHOWING it.
--
-- §15(3)(b) is a different remedy and is NOT this. A discount given AFTER the
-- supply is excluded only where it was established in an agreement at or before
-- the time of supply, is specifically linked to the invoices, and the recipient
-- has REVERSED the attributable input tax credit. That is the §34 credit-note
-- path, which the product already has. Conflating the two would let a
-- post-supply discount reduce the value of a supply already made, with no
-- credit note, no linkage and no reversal at the other end — which is exactly
-- what §15(3)(b) exists to prevent. No discount column is added to the credit
-- or debit note tables for that reason.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THE AMOUNT IS STORED AND THE PERCENTAGE IS ONLY A DISCLOSURE
-- ═══════════════════════════════════════════════════════════════════════════
-- `discount_paise` is the figure the arithmetic uses and it is always stored.
-- `discount_percent_bps` records HOW it was arrived at, because that is what a
-- customer's copy shows ("Less: Trade discount 5%") and what the price list is
-- reconciled against — but it is never re-derived from. A percentage of an
-- integer paise amount does not generally land on an integer, so recomputing
-- the amount from the percentage at read time would give a different number to
-- the one the tax was charged on.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THE GROSS IS NOT STORED
-- ═══════════════════════════════════════════════════════════════════════════
-- `taxable_amount_paise` holds the NET, which is the value of supply and what
-- every downstream reader already means by it — the journal, GSTR-1, the
-- ledgers and the ageing. The gross is `taxable_amount_paise + discount_paise`
-- by construction, so a third column could only ever disagree with the other
-- two.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THE DOCUMENT-LEVEL DISCOUNT IS ALSO ON THE LINES
-- ═══════════════════════════════════════════════════════════════════════════
-- GST is charged per line at the line's own rate, so a document discount that
-- stayed at document level could not be taxed at all on an invoice whose lines
-- carry different rates. It is allocated pro-rata across the lines BEFORE tax
-- and lands in each line's `discount_paise`; `client_sales_invoices.
-- discount_paise` is its total and exists so the invoice can print the footer
-- line the customer was shown. The allocation uses largest-remainder so the
-- parts sum to the whole exactly — a pro-rata split that loses a paise makes
-- the invoice total differ from the figure the customer was quoted.

BEGIN;

ALTER TABLE public.client_sales_invoice_lines
  ADD COLUMN IF NOT EXISTS discount_paise        BIGINT  NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS discount_percent_bps  INTEGER;

ALTER TABLE public.client_sales_invoices
  ADD COLUMN IF NOT EXISTS discount_paise        BIGINT  NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS discount_percent_bps  INTEGER;

-- A discount is money taken OFF, so it is never negative, and it can never
-- exceed the gross — a line discounted past its own value would carry a
-- negative value of supply, which neither the GL nor GSTR-1 can represent.
-- The gross is taxable + discount, so "not more than the gross" is exactly
-- "taxable is not negative", which the second constraint says directly.
ALTER TABLE public.client_sales_invoice_lines
  DROP CONSTRAINT IF EXISTS client_sales_invoice_lines_discount_non_negative;
ALTER TABLE public.client_sales_invoice_lines
  ADD CONSTRAINT client_sales_invoice_lines_discount_non_negative
  CHECK (discount_paise >= 0 AND taxable_amount_paise >= 0);

ALTER TABLE public.client_sales_invoices
  DROP CONSTRAINT IF EXISTS client_sales_invoices_discount_non_negative;
ALTER TABLE public.client_sales_invoices
  ADD CONSTRAINT client_sales_invoices_discount_non_negative
  CHECK (discount_paise >= 0);

-- 0 bps is "no percentage was used" only when discount_paise is 0 too; a flat
-- amount leaves the percentage NULL. 10000 bps is 100%, which is a legitimate
-- free-of-charge line and is where the range stops.
ALTER TABLE public.client_sales_invoice_lines
  DROP CONSTRAINT IF EXISTS client_sales_invoice_lines_discount_percent_range;
ALTER TABLE public.client_sales_invoice_lines
  ADD CONSTRAINT client_sales_invoice_lines_discount_percent_range
  CHECK (discount_percent_bps IS NULL
         OR (discount_percent_bps >= 0 AND discount_percent_bps <= 10000));

ALTER TABLE public.client_sales_invoices
  DROP CONSTRAINT IF EXISTS client_sales_invoices_discount_percent_range;
ALTER TABLE public.client_sales_invoices
  ADD CONSTRAINT client_sales_invoices_discount_percent_range
  CHECK (discount_percent_bps IS NULL
         OR (discount_percent_bps >= 0 AND discount_percent_bps <= 10000));

COMMENT ON COLUMN public.client_sales_invoice_lines.discount_paise IS
    'Discount excluded from the value of supply under CGST §15(3)(a) — given '
    'before or at the time of supply and recorded in the invoice. Includes this '
    'line''s pro-rata share of any document-level discount. The line''s gross is '
    'taxable_amount_paise + discount_paise. Migration 364.';
COMMENT ON COLUMN public.client_sales_invoice_lines.discount_percent_bps IS
    'How the discount was arrived at, for the customer''s copy — NULL when a '
    'flat amount was entered. Never re-derived from: a percentage of an integer '
    'paise amount does not generally land on an integer. Migration 364.';
COMMENT ON COLUMN public.client_sales_invoices.discount_paise IS
    'Total of the lines'' discount_paise, so the invoice can print the footer '
    'line the customer was shown. Migration 364.';

COMMIT;
