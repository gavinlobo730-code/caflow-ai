-- Rollback of migration 496: drops the three policies it created. THIS RE-OPENS THE HOLE: anyone who may write tax audits
-- can again record one as completed or filed, reopen a completed one and delete it with their own sign-in.
DROP POLICY IF EXISTS "tax_audits_state_tier_insert" ON public.tax_audits;
DROP POLICY IF EXISTS "tax_audits_state_tier_update" ON public.tax_audits;
DROP POLICY IF EXISTS "tax_audits_state_tier_delete" ON public.tax_audits;
