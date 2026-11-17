-- Migration 706: a hub worklist leaves the firm's own practice out of the clients it lists (ledger POST-A-457, Guardrail G2).
--
-- WHAT WAS WRONG
-- The firm's own practice is a `clients` row (`is_internal = true`), and Guardrail G2 says it is not one of the firm's clients to count,
-- list, score or chase (docs/architecture/11-revenue-ops-and-knowledge.md, section 3). `hub_client_worklist` (the guarded wrapper of
-- migration 486 over migration 432's body, renamed `hub_client_worklist__unguarded`) left it out only for a signed-in caller who is not a
-- Partner. For a Partner, and for the API's service-role call (no `auth.uid()`), it was listed among the firm's clients on every hub tile
-- (its unreconciled bank lines, what its customers owe it, its undepreciated assets, its open year end), and the count beside the list
-- (`hub_worklist_service._client_count`) counted it too.
--
-- WHAT THIS DOES
-- Replaces the WRAPPER only, derived from migration 486, its last definition (`grep -ln "FUNCTION.*hub_client_worklist"
-- migrations/*.sql | sort | tail -1`), and changes one statement of it: the rows the unguarded body returns are handed back without
-- the row of any client marked `is_internal`. The narrowing of a signed-in caller who is not a Partner is kept exactly, and the body
-- is untouched, so nothing it answers changes for any other client. The wrapper is dropped and created again with a plain CREATE, as 486 created
-- it (the tile guard in `tests/test_the_firm_hub_tiles_land_somewhere.py` treats a replace of either name as a new definition of the
-- tile LOGIC, which this is not); the grants are restated as 486 left them, and nothing depends on the wrapper. `services/hub_worklist_service._python_twin` leaves the practice out the same way, and the parity test holds the two together.
--
-- Read-only. No table is created, altered or written. Reversible: 706_..._rollback.sql restores migration 486's wrapper.

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
    -- Since migration 706 nobody, a Partner and the service role included, is given a row for the firm's own practice: it is not
    -- one of the firm's clients (Guardrail G2). Only the practice's row is removed; every other row is the body's, unchanged.
    RETURN QUERY
    SELECT w.client_id, w.signal
      FROM public.hub_client_worklist__unguarded(p_firm, p_tile, v_ids) AS w
     WHERE NOT EXISTS (SELECT 1 FROM public.clients c WHERE c.id = w.client_id AND c.is_internal);
END;
$fn$;

REVOKE ALL ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) TO authenticated, service_role;
