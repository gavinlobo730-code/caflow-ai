-- Rollback for 402.
--
-- Both columns are nullable with no default and nothing was back-filled, so
-- dropping them loses only what a CA recorded after 402 was applied. The
-- engine reads NULL as "not recorded" and reports the gap, which is exactly
-- the state every row was in before it.

ALTER TABLE public.capital_gains
  DROP CONSTRAINT IF EXISTS capital_gains_fmv_31_01_2018_paise_check;

ALTER TABLE public.capital_gains
  DROP COLUMN IF EXISTS fmv_31_01_2018_paise;

ALTER TABLE public.capital_gains
  DROP COLUMN IF EXISTS is_listed_security;
