-- Rollback for 342.
--
-- The re-classification is NOT reversed. Putting an overdraft back under Assets
-- would restore a wrong balance sheet, and the classification is correct
-- independently of the code that reads it. Reverse it by hand, per account, if
-- an account really was mis-set as Cash Credit.

DROP INDEX IF EXISTS public.idx_receipts_bank_account;
DROP INDEX IF EXISTS public.idx_purchase_payments_bank_account;

ALTER TABLE public.receipts          DROP COLUMN IF EXISTS bank_account_id;
ALTER TABLE public.purchase_payments DROP COLUMN IF EXISTS bank_account_id;
