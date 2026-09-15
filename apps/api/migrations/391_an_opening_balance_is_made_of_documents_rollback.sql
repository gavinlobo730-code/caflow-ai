-- Rollback for 391 — an opening balance is made of documents (ACC-14).
--
-- REFUSES while any opening document exists. Dropping the column would not
-- delete those rows: it would turn each of them into an ORDINARY invoice or
-- bill — which is a document whose revenue and GST this client's next GSTR-1
-- would declare for a second time, and whose input credit its Table 4(A) would
-- claim again. A silent rollback here files a wrong return.
--
-- To roll back deliberately: delete the opening documents first (the Opening
-- Balances screen removes them), then run this.

BEGIN;

DO $$
DECLARE n_inv BIGINT; n_bill BIGINT;
BEGIN
  SELECT count(*) INTO n_inv  FROM public.client_sales_invoices WHERE is_opening;
  SELECT count(*) INTO n_bill FROM public.purchase_bills        WHERE is_opening;
  IF n_inv > 0 OR n_bill > 0 THEN
    RAISE EXCEPTION
      'Refusing to roll back 391: % opening invoice(s) and % opening bill(s) '
      'exist. Dropping is_opening would turn each into an ordinary document, '
      'and the next GST return would declare its supply and claim its credit a '
      'second time. Delete the opening documents first.', n_inv, n_bill;
  END IF;
END $$;

DROP INDEX IF EXISTS public.idx_client_sales_invoices_opening;
DROP INDEX IF EXISTS public.idx_purchase_bills_opening;

ALTER TABLE public.client_sales_invoices DROP COLUMN IF EXISTS is_opening;
ALTER TABLE public.purchase_bills        DROP COLUMN IF EXISTS is_opening;

COMMIT;
