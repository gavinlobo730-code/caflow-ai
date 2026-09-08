-- Rollback for migration 339: drop the two cash columns from gstr3b_returns.
--
-- WHAT THIS LOSES is the record of what was actually paid. After this,
-- filings.tax_payable_paise reverts to the Table 6 set-off residual, which for
-- any return carrying reverse charge is smaller than the challan — §49(4) with
-- §2(82) makes §9(3)/(4) tax payable in cash and the set-off cannot touch it.
--
-- Idempotent, and safe to re-run.

ALTER TABLE public.gstr3b_returns
  DROP COLUMN IF EXISTS rcm_cash_paise,
  DROP COLUMN IF EXISTS cash_payable_paise;
