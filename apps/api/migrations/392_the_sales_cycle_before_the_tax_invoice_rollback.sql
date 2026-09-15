-- Rollback for 392 — the sales cycle before the tax invoice (SALES-21).
--
-- REFUSES while any delivery challan is OUTSTANDING on a clock. Dropping the
-- table would not merely lose a document: CGST s.143(3)/(4) deems goods still
-- with a job worker after one year (three for capital goods) to have been
-- SUPPLIED on the day they were sent out, and s.31(7) puts a six-month limit
-- on goods sent on approval. The challan is the only record either period can
-- be run against — there is no journal, no stock movement and no invoice — so
-- a silent drop makes a deemed supply permanently invisible, and the tax on it
-- falls due in a return that has already been filed.
--
-- Quotations, proforma invoices and sales orders carry no such clock and are
-- dropped with the rest once the challans are dealt with.
--
-- To roll back deliberately: record the date each outstanding challan's goods
-- came back (or cancel a challan raised in error), then run this.

BEGIN;

DO $$
DECLARE n BIGINT;
BEGIN
  SELECT count(*) INTO n
    FROM public.delivery_challans
   WHERE received_back_on IS NULL
     AND status IN ('draft', 'issued')
     AND reason IN ('job_work', 'sale_on_approval');
  IF n > 0 THEN
    RAISE EXCEPTION
      'Refusing to roll back 392: % delivery challan(s) are still outstanding '
      'on a s.143 or s.31(7) period. Dropping the table loses the only record '
      'either clock can be run against, and the deemed supply it hides falls '
      'due on the challan date — in a return already filed. Record the goods '
      'coming back, or cancel the challan, first.', n;
  END IF;
END $$;

DROP TABLE IF EXISTS public.delivery_challan_lines;
DROP TABLE IF EXISTS public.delivery_challans;
DROP TABLE IF EXISTS public.sales_order_lines;
DROP TABLE IF EXISTS public.sales_orders;
DROP TABLE IF EXISTS public.sales_quotation_lines;
DROP TABLE IF EXISTS public.sales_quotations;

COMMIT;
