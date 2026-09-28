-- Migration 432: the hub counts only what is OWED, and Sales has a worklist.
--
-- Derived from migration 416, the LAST definer of `hub_client_worklist`
-- (`grep -ln "FUNCTION.*hub_client_worklist" migrations/*.sql | sort | tail -1`
-- before this file). A replaced function loses its whole old body, so every
-- clause of 416 is carried forward below — the SECURITY DEFINER firm
-- check, the fixed search_path, the four existing branches, the refusal of an
-- unknown tile, the COMMENT, both REVOKEs and the GRANT. Two branches change
-- and one is added; nothing else moves.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG, 1: A CANCELLED BILL WAS STILL OWED (accounting-hub-1-02)
-- ═══════════════════════════════════════════════════════════════════════════
-- `purchase_bills.outstanding_paise` is GENERATED (migration 278) from the
-- money columns alone — net payable, credit notes, paid, debited — and knows
-- nothing about `status` or `deleted_at`. So a CANCELLED bill keeps its whole
-- face value as "outstanding", a DRAFT bill (never received, never posted)
-- carries one too, and a soft-deleted row carries whatever it had when it was
-- discarded. 416's `purchases` branch filtered on `outstanding_paise > 0`
-- alone and counted all three, while AP ageing — the screen a CA would check
-- the figure against — has always excluded them
-- (`vendor_statement_service._DEAD_BILL = {"draft", "cancelled"}` with
-- `.is_("deleted_at", "null")`). Measured in production on 27-09-2026: the
-- firm-wide Purchases figure carried 4 cancelled bills (₹7,20,725.35) and 2
-- drafts (₹71,036.00) — ₹7.92 lakh the practice's clients do not owe anybody.
-- The Sales figure had the same gap over `client_sales_invoices`: 4
-- soft-deleted drafts (₹78,054.64) and 1 cancelled invoice (₹118.00).
--
-- The rule is now the ageing screens' rule, in all three places that compute
-- the figure: `status NOT IN ('draft', 'cancelled') AND deleted_at IS NULL`.
-- `services/hub_service._DEAD_DOCUMENT` is the vocabulary,
-- `tests/test_the_hub_asks_the_right_table_pg.py` holds it against both
-- tables' CHECKs, and `tests/test_the_firm_hub_tiles_land_somewhere.py` holds
-- this file's text against it.
--
-- ⚠️ `NOT IN` NAMES THE DEAD STATES AND COMPLEMENTS, `_outstanding()`'s own
-- rule turned round: a status added to either CHECK is almost always a new
-- LIVE state (a disputed bill is still owed), so it joins the figure
-- automatically instead of silently leaving it. `status` is NOT NULL with a
-- default on both tables, so the three-valued `NOT IN` cannot drop a row.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG, 2: THE SALES TILE OPENED THE PRACTICE'S OWN FEES
-- (accounting-hub-2-05)
-- ═══════════════════════════════════════════════════════════════════════════
-- The Sales tile — "Overdue from customers", summed over the CLIENTS' own
-- `client_sales_invoices` — linked to `/accounting/receivables`, which reads
-- `fee_invoices`: what the clients owe the PRACTICE. A client whose customers
-- owe it ₹19.9 crore showed ₹0 there, on a screen the tile's number sent the
-- CA to. 416 gave Banking, Purchases, Fixed Assets and Year-End a worklist and
-- left Sales out on the belief that `/accounting/receivables` already answered
-- its question (`lib/navigation/screens.ts` said so in as many words). It
-- answered a different question.
--
-- So Sales gets the same queue Purchases has — one row per client, the SUM of
-- what its customers still owe it, opening that client's Sales section — at
-- `/accounting/invoices`, replacing the last `MovedToClientWorkspace`
-- tombstone exactly as 416's fixed-asset worklist replaced the other.
--
-- ⚠️ THE FIGURE IS EVERYTHING OUTSTANDING, NOT ONLY WHAT IS PAST DUE, on both
-- money tiles, although both tiles' questions say "Overdue". That is 416's
-- behaviour for Purchases carried to Sales unchanged; whether the tiles should
-- filter on `due_date` or be relabelled is an open owner decision and is not
-- taken as a side effect of this migration.
--
-- One no-op is dropped: 416's purchases branch opened with
-- `SELECT NULL INTO v_my_firm WHERE FALSE`, which assigns NULL to a variable
-- nothing reads after the firm check. It changed nothing and says nothing.
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
    -- every Executive. The service passes `core.authz.effective_client_ids` as
    -- `p_client_ids`, which gives an Executive their own book and nobody
    -- else's.
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

    ELSIF p_tile = 'sales' THEN
        -- What each client's CUSTOMERS still owe it. Not `fee_invoices`, which
        -- is what the clients owe the practice — see the header.
        RETURN QUERY
        SELECT s.client_id, SUM(s.outstanding_paise)::bigint
          FROM public.client_sales_invoices s
         WHERE s.firm_id = p_firm
           AND s.client_id IS NOT NULL
           AND (p_client_ids IS NULL OR s.client_id = ANY (p_client_ids))
           AND s.outstanding_paise > 0
           AND s.status NOT IN ('draft', 'cancelled')
           AND s.deleted_at IS NULL
         GROUP BY s.client_id;

    ELSIF p_tile = 'purchases' THEN
        RETURN QUERY
        SELECT b.client_id, SUM(b.outstanding_paise)::bigint
          FROM public.purchase_bills b
         WHERE b.firm_id = p_firm
           AND b.client_id IS NOT NULL
           AND (p_client_ids IS NULL OR b.client_id = ANY (p_client_ids))
           AND b.outstanding_paise > 0
           AND b.status NOT IN ('draft', 'cancelled')
           AND b.deleted_at IS NULL
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
    'The two money tiles count a live document only (status not draft or '
    'cancelled, not soft-deleted), the ageing screens'' rule. '
    'Migrations 416 and 432.';

REVOKE EXECUTE ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.hub_client_worklist(uuid, text, uuid[]) FROM anon;
GRANT EXECUTE ON FUNCTION public.hub_client_worklist(uuid, text, uuid[])
    TO authenticated, service_role;
