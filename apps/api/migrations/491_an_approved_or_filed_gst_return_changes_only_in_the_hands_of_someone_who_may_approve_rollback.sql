-- Rollback of migration 491: drops the six policies it created. THIS RE-OPENS THE HOLE: anyone who may compute GST
-- returns can again approve one, mark one filed, reopen an approved or filed one and delete a filed one with their own
-- sign-in. Only for a database that must be put back exactly as it was before 491.
DROP POLICY IF EXISTS "gstr1_returns_state_tier_insert" ON public.gstr1_returns;
DROP POLICY IF EXISTS "gstr1_returns_state_tier_update" ON public.gstr1_returns;
DROP POLICY IF EXISTS "gstr1_returns_state_tier_delete" ON public.gstr1_returns;
DROP POLICY IF EXISTS "gstr3b_returns_state_tier_insert" ON public.gstr3b_returns;
DROP POLICY IF EXISTS "gstr3b_returns_state_tier_update" ON public.gstr3b_returns;
DROP POLICY IF EXISTS "gstr3b_returns_state_tier_delete" ON public.gstr3b_returns;
