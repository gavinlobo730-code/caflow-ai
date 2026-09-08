-- Rollback for 341.
--
-- Restores the 340 natural key, which is the DEFECTIVE one — a credit note and
-- a debit note sharing a number will collide again, and the delete-then-insert
-- in reconcile_2b will lose the period. Rolling back is therefore only correct
-- alongside reverting the service change that this migration exists to support.

DROP TABLE IF EXISTS public.gstr2b_reconciliations;

DROP INDEX IF EXISTS public.uq_gstr2a_records_document;
CREATE UNIQUE INDEX IF NOT EXISTS uq_gstr2a_records_document
  ON public.gstr2a_records
     (client_id, return_period, section, supplier_gstin, invoice_number);
