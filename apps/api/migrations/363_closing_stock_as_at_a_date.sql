-- Migration 363: what the stock was worth on a date.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING (INV-01)
-- ═══════════════════════════════════════════════════════════════════════════
-- Nothing anywhere answered "what stock did this client hold on 31 March, and
-- what was it worth". `list_stock_items` takes no date and returns today's
-- position; `get_stock_ledger` takes a date RANGE but only to filter rows.
-- So at year end the CA cannot produce the stock statement that ties to the
-- Inventories line on the balance sheet, and cannot attach the quantitative
-- details working paper §44AB expects. Tally's Stock Summary is as-at-a-date
-- by definition and is the report an SME's accountant lives in.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY IT SUMS THE DELTAS AND NEVER READS THE RUNNING COLUMNS
-- ═══════════════════════════════════════════════════════════════════════════
-- `inventory_stock_ledger` carries BOTH a per-movement delta and a stored
-- running total, and only the delta can answer this question.
--
-- The running totals are chained in INSERTION order — `_last_ledger_row`
-- orders by `created_at` and says at length why: a bill dated 1 July received
-- on 15 July, after a 10 July sale was already recorded, must not fall out of
-- the chain. That is the right rule for a perpetual system, and it means the
-- stored running column on a row is the position as at the moment that row was
-- RECORDED, not as at its movement_date. Taking the running total off the last
-- row on or before a date therefore answers a question nobody asked.
--
-- The deltas have no such problem: addition commutes. Σ quantity_delta and
-- Σ value_delta_paise over `movement_date <= D` are the same numbers whatever
-- order the rows went in.
--
-- And they are the RIGHT numbers, for a reason that is not a coincidence:
-- `post_cogs_journal_entry` / `post_inventory_journal_entry` post exactly
-- `value_delta_paise`, dated exactly `movement_date`. So Σ value_delta_paise
-- to D IS the movement on the Inventory control account to D. The stock
-- statement and the balance sheet tie by construction rather than by luck —
-- which is the whole point of the report.
--
-- Two invariants this rests on, both already enforced in the costing code:
--   * `_compute_stock_out` force-closes to zero on the last unit out and says
--     "the deltas always sum to the running value" — so over an item's WHOLE
--     history this function and the stored running total agree exactly.
--   * `_compute_stock_in` carries any true-up out of the delta for the same
--     reason.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A SQL FUNCTION AND NOT PYTHON
-- ═══════════════════════════════════════════════════════════════════════════
-- CLAUDE.md's reporting rule: what crosses the wire is proportional to the
-- size of the ANSWER, not the size of the ledger. A stock summary is one row
-- per item — dozens — while the ledger behind it is one row per movement, for
-- years. `domain/reporting/stock_position.py` is the identical rule for mock
-- mode, where there is no DATABASE_URL and no SQL functions, and
-- `tests/test_stock_position_parity_pg.py` holds the two identical.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IT DOES NOT DO
-- ═══════════════════════════════════════════════════════════════════════════
-- It does not hide an item whose position is nil. An item with movements on or
-- before the date appears with whatever quantity and value it has, zero
-- included. Dropping nil lines is a display choice, and a report that silently
-- omits rows cannot be tied to a control account by someone who does not know
-- which rows it dropped.

BEGIN;

CREATE OR REPLACE FUNCTION public.stock_position_as_at(
    p_firm   uuid,
    p_client uuid,
    p_as_of  date,
    p_item   uuid DEFAULT NULL
) RETURNS jsonb
LANGUAGE plpgsql STABLE SECURITY DEFINER
SET search_path = public, pg_catalog
AS $fn$
DECLARE
    v_my_firm  uuid;
    v_internal uuid;
    v_out      jsonb;
BEGIN
    -- Restates the RLS that SECURITY DEFINER bypasses. Transcribed from
    -- schedule_iii_ageing (migration 303), which took it from cash_flow_report
    -- (279) and post_journal_atomic (271), so the four cannot drift in what
    -- they consider an authorised caller.
    IF auth.uid() IS NOT NULL THEN
        v_my_firm := public.get_my_firm_id();

        IF v_my_firm IS NULL THEN
            RAISE EXCEPTION 'stock_position_as_at: caller has no user record in this database'
                USING ERRCODE = '42501';
        END IF;

        IF p_firm IS DISTINCT FROM v_my_firm THEN
            RAISE EXCEPTION 'stock_position_as_at: firm % is not the caller''s firm', p_firm
                USING ERRCODE = '42501';
        END IF;

        IF NOT public.can_access_client(p_client::text) THEN
            RAISE EXCEPTION 'stock_position_as_at: client % is not assigned to the caller', p_client
                USING ERRCODE = '42501';
        END IF;

        v_internal := public.my_internal_client_id();
        IF v_internal IS NOT NULL
           AND p_client = v_internal
           AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
            RAISE EXCEPTION 'stock_position_as_at: only a Partner may read the firm''s internal client'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    SELECT (
    WITH pos AS (
        SELECT l.service_catalogue_id                     AS item_id,
               SUM(l.quantity_delta)                      AS qty,
               SUM(l.value_delta_paise)                   AS value_paise,
               MAX(l.movement_date)                       AS last_movement_date,
               COUNT(*)                                   AS movements
          FROM public.inventory_stock_ledger l
         WHERE l.firm_id = p_firm
           AND l.client_id = p_client
           AND l.movement_date <= p_as_of
           AND (p_item IS NULL OR l.service_catalogue_id = p_item)
         GROUP BY l.service_catalogue_id
    ),
    named AS (
        SELECT p.item_id,
               COALESCE(c.name, '(deleted item)')         AS name,
               c.unit                                     AS unit,
               c.hsn_sac                                  AS hsn_sac,
               p.qty,
               p.value_paise,
               p.last_movement_date,
               p.movements,
               -- The average is DERIVED at the end, never accumulated: an
               -- average of averages is not an average. Nil or negative
               -- quantity has no meaningful unit cost, and reporting one
               -- computed by dividing by a negative would put a negative cost
               -- on the working paper.
               CASE WHEN p.qty > 0
                    THEN round(p.value_paise::numeric / p.qty)::bigint
                    ELSE 0::bigint
               END                                        AS avg_cost_paise
          FROM pos p
          LEFT JOIN public.service_catalogue c
                 ON c.id = p.item_id
                AND c.firm_id = p_firm
                AND c.client_id = p_client
    )
    SELECT jsonb_build_object(
        'as_of', p_as_of,
        'items', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                       'service_catalogue_id', n.item_id,
                       'name',                 n.name,
                       'unit',                 n.unit,
                       'hsn_sac',              n.hsn_sac,
                       'qty_units',            n.qty,
                       'value_paise',          n.value_paise,
                       'avg_cost_paise',       n.avg_cost_paise,
                       'last_movement_date',   n.last_movement_date,
                       'movements',            n.movements)
                   ORDER BY n.name, n.item_id)
              FROM named n), '[]'::jsonb),
        -- The figure that ties to the Inventory control account. Summed from
        -- the same deltas rather than from the rounded per-item averages —
        -- qty * avg_cost re-rounds an already-rounded average and drifts a few
        -- paise per item, which across a register no longer ties.
        'total_value_paise', COALESCE((SELECT SUM(n.value_paise) FROM named n), 0),
        'total_items',       COALESCE((SELECT COUNT(*) FROM named n), 0)
    )) INTO v_out;

    RETURN v_out;
END
$fn$;

COMMENT ON FUNCTION public.stock_position_as_at(uuid, uuid, date, uuid) IS
    'Closing stock as at a date: quantity, value and derived average cost per '
    'item, summed from inventory_stock_ledger''s DELTAS (order-independent) '
    'rather than from its stored running totals (chained in insertion order, '
    'so meaningless as at a movement_date). Ties to the Inventory control '
    'account by construction, because the inventory journal posts '
    'value_delta_paise at movement_date. One row per item, per CLAUDE.md''s '
    'reporting rule. domain/reporting/stock_position.py is the identical rule '
    'for mock mode and the two are pinned by '
    'tests/test_stock_position_parity_pg.py. Migration 363.';

REVOKE EXECUTE ON FUNCTION public.stock_position_as_at(uuid, uuid, date, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.stock_position_as_at(uuid, uuid, date, uuid) FROM anon;
GRANT EXECUTE ON FUNCTION public.stock_position_as_at(uuid, uuid, date, uuid)
    TO authenticated, service_role;

-- The aggregate walks one client's movements up to a date. The existing index
-- is (service_catalogue_id, movement_date, created_at), which serves the
-- per-item drill-down; the whole-register summary filters on client and date
-- first, and had no index at all.
CREATE INDEX IF NOT EXISTS idx_inventory_stock_ledger_client_date
    ON public.inventory_stock_ledger (client_id, movement_date)
    INCLUDE (service_catalogue_id, quantity_delta, value_delta_paise);

COMMIT;
