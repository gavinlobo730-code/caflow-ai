-- Rollback of migration 706: restores migration 486's wrapper of `hub_client_worklist`, which leaves the practice out for a signed-in
-- caller who is not a Partner only. Copied from migration 486 unchanged.

DROP FUNCTION public.hub_client_worklist(uuid, text, uuid[]);

CREATE FUNCTION public.hub_client_worklist(p_firm uuid, p_tile text, p_client_ids uuid[] DEFAULT NULL)
RETURNS TABLE (client_id uuid, signal bigint)
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_ids uuid[];
BEGIN
    PERFORM public.assert_caller_acts_for('hub_client_worklist', p_firm, NULL, NULL);
    v_ids := p_client_ids;
    -- The function checks the FIRM and then filters by the client ids it is GIVEN. A signed-in caller who is not a
    -- Partner is narrowed to the clients they can reach, and never to the firm's internal practice client, whatever
    -- they passed (a NULL list means "all of them", which for them means all of THEIRS). The application's own
    -- caller already passes exactly that list, so for it nothing changes.
    IF auth.uid() IS NOT NULL AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
        v_ids := ARRAY(SELECT c.id FROM public.clients c
                        WHERE c.firm_id = p_firm
                          AND (p_client_ids IS NULL OR c.id = ANY (p_client_ids))
                          AND public.can_access_client(c.id::text)
                          AND c.id IS DISTINCT FROM public.my_internal_client_id());
    END IF;
    RETURN QUERY SELECT * FROM public.hub_client_worklist__unguarded(p_firm, p_tile, v_ids);
END;
$fn$;

REVOKE ALL ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) TO authenticated, service_role;
