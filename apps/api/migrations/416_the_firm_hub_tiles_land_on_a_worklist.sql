-- Migration 416: which of my clients needs work in this module.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING (question G3, answered as D22)
-- ═══════════════════════════════════════════════════════════════════════════
-- Five of D1's fifteen hub tiles had no firm-level destination at all —
-- Banking, Purchases, Fixed Assets, Inventory and Year-End — and two of those
-- five landed on a `MovedToClientWorkspace` TOMBSTONE, a page whose whole
-- content is "this moved". So the firm hub showed "7 assets with depreciation
-- outstanding" with nowhere to click.
--
-- The tombstones are a deliberate earlier decision ("firm-level accounting
-- screens have been retired; accounting flows through the client workspace"),
-- so the answer is not a rebuilt firm-level register. It is the question a
-- bureau actually asks on the 3rd of the month: WHICH of my clients needs work
-- in this module. `domain/hub/worklist.py` is the authority for which tiles
-- have one and what a row means; this function is the only place that knows
-- which table answers it.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A SQL FUNCTION AND NOT PYTHON
-- ═══════════════════════════════════════════════════════════════════════════
-- CLAUDE.md's reporting rule: what crosses the wire is proportional to the
-- ANSWER, not the ledger. The answer is ONE ROW PER CLIENT — dozens — and the
-- populations behind it are one row per bank statement line, per purchase
-- bill, per asset, per engagement, for years. PostgREST has no GROUP BY, so
-- the two shapes available in Python are a COUNT per client (N cross-region
-- round trips, Singapore to Mumbai, once per client) or paging every
-- outstanding row and tallying here (proportional to the ledger). Both are
-- what this rule exists to forbid. `GROUP BY client_id` server-side is the
-- third option the rule names, and `services/hub_worklist_service.py` holds
-- the mock-mode twin with a parity test over both.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE PREDICATES ARE TRANSCRIBED FROM `services/hub_service._signals`
-- ═══════════════════════════════════════════════════════════════════════════
-- Each branch below computes exactly what that tile's figure is, because two
-- definitions of "a bank line still needing a person" is how a tile and the
-- screen it opens come to disagree about the number in between them — and a CA
-- who clicks 7 and counts 5 stops trusting both.
-- `tests/test_the_firm_hub_tiles_land_somewhere.py` holds the transcription
-- against that module's own vocabulary, so a status added to a CHECK fails
-- there rather than drifting here:
--
--   banking       bank_transactions      entry_state IN domain/banking/entry.OPEN_STATES
--   purchases     purchase_bills         SUM(outstanding_paise) WHERE > 0
--   fixed_assets  fixed_assets           depreciation_posted_through IS NULL
--   year_end      year_end_engagements   status <> 'locked'
--
-- ⚠️ EACH IS THE COMPLEMENT OF THE FINISHED STATES, not a list of the
-- unfinished ones — `_outstanding()`'s own rule. A value added to one of those
-- CHECKs is almost always a new intermediate state, and complementing makes it
-- join the outstanding count automatically instead of being dropped.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- A CLIENT WITH NOTHING OUTSTANDING IS NOT RETURNED
-- ═══════════════════════════════════════════════════════════════════════════
-- Deliberate, and the opposite of `stock_position_as_at`'s rule for the same
-- reason it is the opposite: that function reports a POSITION, where a nil is
-- a fact worth stating, and this one reports a QUEUE, where every row is work.
-- A forty-client firm with three clients needing bank work wants three rows,
-- not forty with thirty-seven zeroes; the screen says how many clients were
-- examined so an empty queue reads as "nothing to do" rather than as a failed
-- fetch. `GROUP BY` gives that by construction — a client with no matching row
-- simply has no group.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- SCOPE
-- ═══════════════════════════════════════════════════════════════════════════
-- `p_client_ids` NULL means NO RESTRICTION (a Partner); an EMPTY array means
-- NOTHING, never "no filter" — the distinction `routers/accounting.py` records
-- and the one that turns a scoping bug into a cross-client read if collapsed.
-- `core.authz.effective_client_ids` answers exactly that shape and the service
-- passes it through unchanged.
--
-- Read-only. No table is created, altered or written.

CREATE OR REPLACE FUNCTION public.hub_client_worklist(
    p_firm       uuid,
    p_tile       text,
    p_client_ids uuid[] DEFAULT NULL
) RETURNS TABLE (client_id uuid, signal bigint)
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_my_firm uuid;
BEGIN
    -- Restates the RLS that SECURITY DEFINER bypasses. Transcribed from
    -- stock_position_as_at (363), which took it from schedule_iii_ageing (303)
    -- and post_journal_atomic (271), so they cannot drift in what they
    -- consider an authorised caller.
    --
    -- ⚠️ THE ASSIGNMENT CHECK FILTERS RATHER THAN RAISES, and that is the one
    -- deliberate difference from 363. That function takes ONE client and a
    -- caller asking for a client they are not assigned to is a bug worth
    -- shouting about; this one is FIRM-scoped by nature, so raising on the
    -- first unassigned client in the firm would make the worklist unusable for
    -- every Executive. `can_access_client` is applied to each returned row
    -- below, which gives an Executive their own book and nobody else's.
    IF auth.uid() IS NOT NULL THEN
        v_my_firm := public.get_my_firm_id();

        IF v_my_firm IS NULL THEN
            RAISE EXCEPTION 'hub_client_worklist: caller has no user record in this database'
                USING ERRCODE = '42501';
        END IF;

        IF p_firm IS DISTINCT FROM v_my_firm THEN
            RAISE EXCEPTION 'hub_client_worklist: firm % is not the caller''s firm', p_firm
                USING ERRCODE = '42501';
        END IF;
    END IF;

    IF p_tile = 'banking' THEN
        RETURN QUERY
        SELECT t.client_id, COUNT(*)::bigint
          FROM public.bank_transactions t
         WHERE t.firm_id = p_firm
           AND t.client_id IS NOT NULL
           AND (p_client_ids IS NULL OR t.client_id = ANY (p_client_ids))
           AND t.entry_state IN ('needs_you', 'proposed', 'ready')
         GROUP BY t.client_id;

    ELSIF p_tile = 'purchases' THEN
        SELECT NULL INTO v_my_firm WHERE FALSE;   -- no-op, keeps the shape flat
        RETURN QUERY
        SELECT b.client_id, SUM(b.outstanding_paise)::bigint
          FROM public.purchase_bills b
         WHERE b.firm_id = p_firm
           AND b.client_id IS NOT NULL
           AND (p_client_ids IS NULL OR b.client_id = ANY (p_client_ids))
           AND b.outstanding_paise > 0
         GROUP BY b.client_id;

    ELSIF p_tile = 'fixed_assets' THEN
        RETURN QUERY
        SELECT a.client_id, COUNT(*)::bigint
          FROM public.fixed_assets a
         WHERE a.firm_id = p_firm
           AND a.client_id IS NOT NULL
           AND (p_client_ids IS NULL OR a.client_id = ANY (p_client_ids))
           AND a.depreciation_posted_through IS NULL
         GROUP BY a.client_id;

    ELSIF p_tile = 'year_end' THEN
        RETURN QUERY
        SELECT e.client_id, COUNT(*)::bigint
          FROM public.year_end_engagements e
         WHERE e.firm_id = p_firm
           AND e.client_id IS NOT NULL
           AND (p_client_ids IS NULL OR e.client_id = ANY (p_client_ids))
           AND e.status <> 'locked'
         GROUP BY e.client_id;

    ELSE
        -- A tile with no worklist is a REFUSAL, not an empty answer. An empty
        -- result would read as "no client needs work", which is the nil
        -- `domain/gst/gstr3b_computer`'s rule is about: a nil meaning nothing
        -- to do and a nil meaning nobody can tell are different facts.
        RAISE EXCEPTION 'hub_client_worklist: % has no firm-level worklist', p_tile
            USING ERRCODE = '22023';
    END IF;
END;
$fn$;

COMMENT ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) IS
    'One row per client that has outstanding work on this hub tile, with the '
    'tile''s own figure. The answer is proportional to the number of CLIENTS, '
    'not to the ledger behind it — CLAUDE.md''s reporting rule. '
    'domain/hub/worklist.py says which tiles have one and why inventory does '
    'not; services/hub_worklist_service.py holds the mock-mode twin and '
    'tests/test_hub_client_worklist_parity_pg.py keeps the two identical. '
    'Migration 416.';

REVOKE EXECUTE ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) FROM anon;
GRANT EXECUTE ON FUNCTION public.hub_client_worklist(uuid, text, uuid[])
    TO authenticated, service_role;
