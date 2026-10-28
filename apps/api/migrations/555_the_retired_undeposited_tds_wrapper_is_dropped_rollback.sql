-- Rollback of migration 555: recreates public.tds_undeposited_paise as migration 523 defined it (a one-line wrapper over the first
-- figure of public.tds_deposit_position), with 523's comment and grants. Nothing calls it; it is restored for fidelity with the schema
-- the earlier API was written against.

CREATE OR REPLACE FUNCTION public.tds_undeposited_paise(p_firm_id uuid, p_client_ids uuid[] DEFAULT NULL)
RETURNS bigint
LANGUAGE sql
STABLE
SECURITY INVOKER
SET search_path = public, pg_temp
AS $$
    SELECT p.undeposited_paise FROM public.tds_deposit_position(p_firm_id, p_client_ids) p;
$$;

COMMENT ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) IS
    'The undeposited_paise of public.tds_deposit_position, kept for the API that was live when migration 523 was applied. Migration 523 changed it to count only quarters for which a challan is recorded. SECURITY INVOKER, read-only.';

REVOKE EXECUTE ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) FROM anon;
GRANT EXECUTE ON FUNCTION public.tds_undeposited_paise(uuid, uuid[]) TO authenticated, service_role;
