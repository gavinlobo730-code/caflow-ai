-- Rollback for 393 — the purchase cycle before the bill (PUR-25).
--
-- REFUSES while any goods receipt exists. Dropping the table does not merely
-- lose a document: the receipt is the only record of WHEN the goods arrived,
-- and two statutes turn on that date —
--
--   * CGST s.16(2)(b) conditions the input tax credit on the goods having been
--     RECEIVED, and
--   * MSMED s.15 runs its fifteen days from the day of ACCEPTANCE, which
--     s.2(b)'s Explanation makes the day of actual DELIVERY.
--
-- Without it `domain/income_tax/section_43b_h.py` falls back to the BILL date,
-- which is EARLIER — so a bill paid in time against its real acceptance date
-- silently becomes a s.43B(h) disallowance, added to taxable income with
-- nothing on the screen saying the date moved.
--
-- The two columns added to `purchase_bill_lines` and `purchase_bills` are
-- dropped with the rest; they hold a link and no figure.
--
-- To roll back deliberately: delete the goods receipts first.

BEGIN;

DO $$
DECLARE n BIGINT;
BEGIN
  SELECT count(*) INTO n FROM public.goods_receipt_notes
   WHERE status <> 'cancelled';
  IF n > 0 THEN
    RAISE EXCEPTION
      'Refusing to roll back 393: % goods receipt(s) exist. They are the only '
      'record of the day the goods arrived, and s.43B(h) falls back to the '
      'earlier BILL date without them — turning bills paid in time into '
      'disallowances with nothing saying the date moved. Delete the receipts '
      'first.', n;
  END IF;
END $$;

DROP INDEX IF EXISTS public.idx_purchase_bill_lines_order_line;
DROP INDEX IF EXISTS public.idx_purchase_bills_order;
ALTER TABLE public.purchase_bill_lines DROP COLUMN IF EXISTS purchase_order_line_id;
ALTER TABLE public.purchase_bills      DROP COLUMN IF EXISTS purchase_order_id;

DROP TABLE IF EXISTS public.goods_receipt_lines;
DROP TABLE IF EXISTS public.goods_receipt_notes;
DROP TABLE IF EXISTS public.purchase_order_lines;
DROP TABLE IF EXISTS public.purchase_orders;

COMMIT;
