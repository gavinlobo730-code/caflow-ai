-- Rollback for migration 374.
--
-- Dropping the columns DESTROYS every recorded compensation cess — the rate
-- limbs and the derived amount alike — and a document's total_paise was
-- written INCLUDING that cess, so after this the header totals no longer
-- reconcile to their own components. Re-applying 374 gives the columns back
-- empty, not restored. Take a backup of the four tables first if any row has
-- a non-zero cess.
--
-- The two ledgers are NOT dropped. A journal already posted against them
-- cannot be un-posted (migration 251's immutability triggers), so removing the
-- account would orphan its lines; and an unused account costs nothing but a
-- row in the chart. Deactivate them by hand if they are genuinely unwanted.

BEGIN;

ALTER TABLE public.client_sales_invoices  DROP COLUMN IF EXISTS cess_paise;
ALTER TABLE public.purchase_bills         DROP COLUMN IF EXISTS cess_paise;

ALTER TABLE public.client_sales_invoice_lines
  DROP COLUMN IF EXISTS cess_rate_bps,
  DROP COLUMN IF EXISTS cess_specific_paise_per_unit,
  DROP COLUMN IF EXISTS cess_paise;

ALTER TABLE public.purchase_bill_lines
  DROP COLUMN IF EXISTS cess_rate_bps,
  DROP COLUMN IF EXISTS cess_specific_paise_per_unit,
  DROP COLUMN IF EXISTS cess_paise;

COMMIT;
