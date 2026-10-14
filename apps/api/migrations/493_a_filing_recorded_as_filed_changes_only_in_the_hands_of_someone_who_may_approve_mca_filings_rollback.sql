-- Rollback of migration 493: drops the three policies it created. THIS RE-OPENS THE HOLE: anyone who may write MCA filings
-- can again record one as filed, reopen a filed one and delete it with their own sign-in.
DROP POLICY IF EXISTS "mca_filings_state_tier_insert" ON public.mca_filings;
DROP POLICY IF EXISTS "mca_filings_state_tier_update" ON public.mca_filings;
DROP POLICY IF EXISTS "mca_filings_state_tier_delete" ON public.mca_filings;
