-- Rollback of migration 522: drops public.tds_undeposited_paise. The hub's TDS tile then has nothing to ask and shows no figure. For
-- fidelity with the previous schema, not for use.
DROP FUNCTION IF EXISTS public.tds_undeposited_paise(uuid, uuid[]);
