-- Rollback for migration 474.
--
-- Drops the keyed-balance table and the ten columns on gstr3b_returns. Rolling
-- back DISCARDS every opening balance a CA keyed and every closing balance a
-- saved return recorded: the next GSTR-3B computes as though the credit ledger
-- opened empty, which over-states the cash payable for any client holding
-- carried-forward credit.

DROP TABLE IF EXISTS public.gst_credit_ledger_openings;

DROP INDEX IF EXISTS public.idx_gstr3b_returns_credit_chain;

ALTER TABLE public.gstr3b_returns
  DROP CONSTRAINT IF EXISTS gstr3b_returns_credit_closing_is_a_set,
  DROP CONSTRAINT IF EXISTS gstr3b_returns_credit_opening_is_a_set,
  DROP CONSTRAINT IF EXISTS gstr3b_returns_credit_is_never_negative,
  DROP CONSTRAINT IF EXISTS gstr3b_returns_credit_opening_source_check;

ALTER TABLE public.gstr3b_returns
  DROP COLUMN IF EXISTS credit_opening_igst_paise,
  DROP COLUMN IF EXISTS credit_opening_cgst_paise,
  DROP COLUMN IF EXISTS credit_opening_sgst_paise,
  DROP COLUMN IF EXISTS credit_opening_cess_paise,
  DROP COLUMN IF EXISTS credit_closing_igst_paise,
  DROP COLUMN IF EXISTS credit_closing_cgst_paise,
  DROP COLUMN IF EXISTS credit_closing_sgst_paise,
  DROP COLUMN IF EXISTS credit_closing_cess_paise,
  DROP COLUMN IF EXISTS credit_closing_as_of,
  DROP COLUMN IF EXISTS credit_opening_source;
