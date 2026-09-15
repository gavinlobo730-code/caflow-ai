-- Rollback for 382.
DROP INDEX IF EXISTS public.idx_bank_txn_gst_declared;

ALTER TABLE public.bank_transactions
  DROP CONSTRAINT IF EXISTS bank_transactions_gst_rate_bps_check;

ALTER TABLE public.bank_transactions
  DROP COLUMN IF EXISTS gst_is_interstate,
  DROP COLUMN IF EXISTS gst_rate_bps;
