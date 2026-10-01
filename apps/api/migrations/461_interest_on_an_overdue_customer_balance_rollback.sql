-- Rollback for 461.
--
-- ⚠️ BOTH HALVES ARE FACTS SOMEBODY TYPED OR A DRAFT WAS RAISED FROM. The rate,
-- grace and basis are a commercial term between a client and its customer, and
-- a charge row is the only record of which period a draft interest invoice
-- covers — drop it and the next preview charges that period again. Export
-- before running this:
--
--   SELECT id, late_interest_rate_bps, late_interest_grace_days, late_interest_from
--     FROM public.customers WHERE late_interest_rate_bps IS NOT NULL;
--   SELECT * FROM public.late_interest_charges;
--
-- No invoice is affected: a draft interest invoice is an ordinary draft sales
-- invoice and stays exactly as it is.

DROP TABLE IF EXISTS public.late_interest_charges;
ALTER TABLE public.customers DROP CONSTRAINT IF EXISTS customers_late_interest_from_check;
ALTER TABLE public.customers DROP CONSTRAINT IF EXISTS customers_late_interest_grace_days_check;
ALTER TABLE public.customers DROP CONSTRAINT IF EXISTS customers_late_interest_rate_bps_check;
ALTER TABLE public.customers
  DROP COLUMN IF EXISTS late_interest_from,
  DROP COLUMN IF EXISTS late_interest_grace_days,
  DROP COLUMN IF EXISTS late_interest_rate_bps;
