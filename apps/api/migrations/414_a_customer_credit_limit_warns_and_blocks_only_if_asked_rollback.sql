-- Rollback for 414. Take a copy of
--   customers(id, credit_limit_paise) WHERE credit_limit_paise IS NOT NULL
-- and invoice_settings(firm_id, credit_limit_blocks) WHERE credit_limit_blocks
-- first: both are facts somebody typed and neither can be re-derived.

ALTER TABLE public.customers
  DROP CONSTRAINT IF EXISTS customers_credit_limit_paise_check;
ALTER TABLE public.customers
  DROP COLUMN IF EXISTS credit_limit_paise;
ALTER TABLE public.invoice_settings
  DROP COLUMN IF EXISTS credit_limit_blocks;
