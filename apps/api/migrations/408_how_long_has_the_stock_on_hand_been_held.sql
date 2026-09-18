-- Migration 408: stock ageing — how long has the stock ON HAND been held.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS MISSING (INV-04), AND WHAT WAS NOT
-- ═══════════════════════════════════════════════════════════════════════════
-- The slow/non-moving half of INV-04 is built: the inventory screen renders
-- Last Moved and Days Idle off migration 363's `stock_position_as_at`. That
-- answers a question about the ITEM.
--
-- Ageing proper is a question about the UNITS. An item selling steadily has a
-- recent last-movement date and may still be carrying forty units bought three
-- years ago behind the ones that keep turning over — and those forty are the
-- obsolescence AS-2 paragraph 24 makes the CA write down to net realisable
-- value. `routers/inventory.py` has offered a write-down endpoint since it was
-- written and gave the CA nothing to decide it on.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY A SQL FUNCTION
-- ═══════════════════════════════════════════════════════════════════════════
-- CLAUDE.md's reporting rule: what crosses the wire is proportional to the
-- ANSWER, not the ledger. This answer is one row per item — dozens — and the
-- input is every movement the client has ever made. The logic is per-row and
-- cannot be pre-bucketed into `account_period_balances`' shape, so it takes
-- `cash_flow_report`'s form rather than a pre-aggregated table.
-- `domain/reporting/stock_ageing.py` is the identical rule for mock mode,
-- where there is no DATABASE_URL and no SQL functions, and
-- `tests/test_stock_ageing_parity_pg.py` holds the two identical.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- THE CONSUMPTION IS AGGREGATE, WHICH IS WHAT MAKES IT ORDER-INDEPENDENT
-- ═══════════════════════════════════════════════════════════════════════════
-- Let T be the total quantity that went OUT over the item's whole history and
-- `cum` the cumulative quantity IN up to and including a receipt. What survives
-- of that receipt is
--
--     LEAST(qty, GREATEST(0, cum - T))
--
-- — a receipt entirely before T is gone, the one straddling it is part
-- consumed, and everything after it is untouched. Σ over the receipts is
-- total_in - T, which is the position migration 363 reports, so the bands sum
-- to the quantity by construction rather than by luck.
--
-- Walking the movements one at a time and decrementing gives the same answer
-- whenever the position is non-negative and DIFFERS only in the oversold case,
-- where the step-by-step walk has to invent a rule for what a later receipt
-- clears first. The aggregate form has no such case.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- AGEING IS FIFO WHATEVER THE CLIENT'S COST FORMULA IS
-- ═══════════════════════════════════════════════════════════════════════════
-- `clients.inventory_costing_method` (migration 394) decides how cost is
-- ASSIGNED to what goes out. This report assigns no cost. It asks a physical
-- question — of the units in the godown today, when did each arrive — and
-- goods leave a godown oldest-first whether or not the books cost them that
-- way. So the assumption is FIFO for every client and nothing here reads the
-- policy.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY THE VALUE IS PRO-RATED RATHER THAN THE LAYER'S OWN COST
-- ═══════════════════════════════════════════════════════════════════════════
-- Having replayed the layers it would be easy to report each one's own
-- `value_delta_paise`. It would also be wrong for most clients: under the
-- weighted average the value that LEFT was the blended cost, so the surviving
-- layers' costs do not sum to the item's carrying amount — and a stock ageing
-- report whose total disagrees with the Inventories line is worse than no
-- report, because somebody will foot it.
--
-- So the quantity bands are the FIFO answer and the VALUE in each is the
-- item's own carrying amount (Σ value_delta_paise, which ties to the Inventory
-- control account because the inventory journal posts exactly that at exactly
-- movement_date) split in proportion to quantity, LARGEST REMAINDER so the
-- parts sum to the whole exactly. Every answer says so.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT IT DOES NOT DO
-- ═══════════════════════════════════════════════════════════════════════════
-- No provision is computed and no write-down percentage is applied: AS-2
-- paragraph 21 makes net realisable value an estimate of selling price less
-- the costs to complete and sell, a fact about the market no ledger holds.
-- Nothing is bucketed by godown or batch — both are on the ledger since
-- migration 398 and neither is what the obsolescence question turns on, and
-- `domain/inventory/batches.py` already ages by EXPIRY, which is the other
-- question. An item whose position is nil or negative reports its position and
-- EMPTY bands with `nothing_on_hand` true, because six zeroes beside a
-- negative quantity read as "no old stock here".

BEGIN;

CREATE OR REPLACE FUNCTION public.stock_ageing_as_at(
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
    -- stock_position_as_at (migration 363), which took it from
    -- schedule_iii_ageing (303), cash_flow_report (279) and
    -- post_journal_atomic (271), so the five cannot drift in what they
    -- consider an authorised caller.
    IF auth.uid() IS NOT NULL THEN
        v_my_firm := public.get_my_firm_id();

        IF v_my_firm IS NULL THEN
            RAISE EXCEPTION 'stock_ageing_as_at: caller has no user record in this database'
                USING ERRCODE = '42501';
        END IF;

        IF p_firm IS DISTINCT FROM v_my_firm THEN
            RAISE EXCEPTION 'stock_ageing_as_at: firm % is not the caller''s firm', p_firm
                USING ERRCODE = '42501';
        END IF;

        IF NOT public.can_access_client(p_client::text) THEN
            RAISE EXCEPTION 'stock_ageing_as_at: client % is not assigned to the caller', p_client
                USING ERRCODE = '42501';
        END IF;

        v_internal := public.my_internal_client_id();
        IF v_internal IS NOT NULL
           AND p_client = v_internal
           AND COALESCE(public.get_my_role(), '') <> 'Partner' THEN
            RAISE EXCEPTION 'stock_ageing_as_at: only a Partner may read the firm''s internal client'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    SELECT (
    WITH movements AS (
        SELECT l.service_catalogue_id AS item_id,
               l.movement_date,
               l.created_at,
               l.id,
               l.quantity_delta,
               l.value_delta_paise
          FROM public.inventory_stock_ledger l
         WHERE l.firm_id = p_firm
           AND l.client_id = p_client
           AND l.movement_date <= p_as_of
           AND (p_item IS NULL OR l.service_catalogue_id = p_item)
    ),
    -- The item's own position and carrying amount, from the SAME deltas
    -- migration 363 sums. These two figures are what the bands must foot to.
    pos AS (
        SELECT item_id,
               SUM(quantity_delta)                                  AS qty,
               SUM(value_delta_paise)                               AS value_paise,
               COALESCE(SUM(-quantity_delta)
                        FILTER (WHERE quantity_delta < 0), 0)       AS total_out
          FROM movements
         GROUP BY item_id
    ),
    -- FIFO order is (movement_date, created_at, id). The third key is what
    -- makes the chain TOTAL — two receipts on one date recorded in one
    -- transaction share a created_at — which matters because the Python twin
    -- must produce the same layer order or the parity test is a coin toss.
    receipts AS (
        SELECT m.item_id,
               m.movement_date,
               m.quantity_delta,
               SUM(m.quantity_delta) OVER (
                   PARTITION BY m.item_id
                   ORDER BY m.movement_date, m.created_at, m.id
                   ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)  AS cum_in
          FROM movements m
         WHERE m.quantity_delta > 0
    ),
    surviving AS (
        SELECT r.item_id,
               r.movement_date,
               LEAST(r.quantity_delta,
                     GREATEST(0::numeric, r.cum_in - p.total_out))    AS qty
          FROM receipts r
          JOIN pos p ON p.item_id = r.item_id
         -- An item with nothing on hand has no bands at all; see the header.
         WHERE p.qty > 0
    ),
    banded AS (
        SELECT s.item_id,
               CASE
                   WHEN (p_as_of - s.movement_date) <= 30  THEN 'd0_30'
                   WHEN (p_as_of - s.movement_date) <= 60  THEN 'd31_60'
                   WHEN (p_as_of - s.movement_date) <= 90  THEN 'd61_90'
                   WHEN (p_as_of - s.movement_date) <= 180 THEN 'd91_180'
                   WHEN (p_as_of - s.movement_date) <= 365 THEN 'd181_365'
                   ELSE 'd365_plus'
               END                                                    AS band,
               SUM(s.qty)                                             AS qty
          FROM surviving s
         WHERE s.qty > 0
         GROUP BY s.item_id, 2
    ),
    -- LARGEST REMAINDER, so the six band values sum to the carrying amount
    -- exactly. Worked on the MAGNITUDE and re-signed, because an oversell can
    -- drive a carrying amount below nil and a floor on a negative rounds the
    -- wrong way.
    weighted AS (
        SELECT b.item_id,
               b.band,
               b.qty,
               p.value_paise,
               SUM(b.qty) OVER (PARTITION BY b.item_id)               AS band_total_qty,
               CASE WHEN p.value_paise < 0 THEN -1 ELSE 1 END         AS sign,
               abs(p.value_paise)                                     AS magnitude
          FROM banded b
          JOIN pos p ON p.item_id = b.item_id
    ),
    exact AS (
        SELECT w.*,
               CASE WHEN w.band_total_qty > 0
                    THEN w.magnitude::numeric * w.qty / w.band_total_qty
                    ELSE 0::numeric
               END                                                    AS share
          FROM weighted w
    ),
    floored AS (
        SELECT e.*,
               floor(e.share)::bigint                                 AS base,
               e.share - floor(e.share)                               AS frac
          FROM exact e
    ),
    ranked AS (
        SELECT f.*,
               f.magnitude - SUM(f.base) OVER (PARTITION BY f.item_id) AS short,
               ROW_NUMBER() OVER (
                   PARTITION BY f.item_id
                   -- Ties go to the band NAMED FIRST in the youngest-to-oldest
                   -- order, which is the same tie-break the Python twin's
                   -- `sorted(..., key=(-frac, index))` takes. Alphabetical
                   -- order on the band key is NOT that order, so the position
                   -- is spelled out.
                   ORDER BY f.frac DESC,
                            CASE f.band
                                WHEN 'd0_30'     THEN 1
                                WHEN 'd31_60'    THEN 2
                                WHEN 'd61_90'    THEN 3
                                WHEN 'd91_180'   THEN 4
                                WHEN 'd181_365'  THEN 5
                                ELSE 6
                            END)                                      AS rn
          FROM floored f
    ),
    final AS (
        SELECT r.item_id,
               r.band,
               r.qty,
               r.sign * (r.base + CASE WHEN r.rn <= r.short THEN 1 ELSE 0 END)
                                                                      AS value_paise
          FROM ranked r
    ),
    oldest AS (
        SELECT s.item_id, MIN(s.movement_date) AS oldest_holding_date
          FROM surviving s
         WHERE s.qty > 0
         GROUP BY s.item_id
    ),
    named AS (
        SELECT p.item_id,
               COALESCE(c.name, '(deleted item)')  AS name,
               COALESCE(c.unit, '')                AS unit,
               p.qty,
               p.value_paise,
               (p.qty <= 0)                        AS nothing_on_hand,
               o.oldest_holding_date
          FROM pos p
          LEFT JOIN public.service_catalogue c
                 ON c.id = p.item_id
                AND c.firm_id = p_firm
                AND c.client_id = p_client
          LEFT JOIN oldest o ON o.item_id = p.item_id
    )
    SELECT jsonb_build_object(
        'as_of', p_as_of,
        'bands', jsonb_build_array('d0_30', 'd31_60', 'd61_90',
                                   'd91_180', 'd181_365', 'd365_plus'),
        'items', COALESCE((
            SELECT jsonb_agg(jsonb_build_object(
                       'service_catalogue_id', n.item_id,
                       'name',                 n.name,
                       'unit',                 n.unit,
                       'qty_units',            n.qty::text,
                       'value_paise',          n.value_paise,
                       'nothing_on_hand',      n.nothing_on_hand,
                       'oldest_holding_date',  n.oldest_holding_date,
                       'band_qty', (
                           SELECT jsonb_object_agg(k, COALESCE(
                               (SELECT f.qty::text FROM final f
                                 WHERE f.item_id = n.item_id AND f.band = k), '0'))
                             FROM unnest(ARRAY['d0_30','d31_60','d61_90',
                                               'd91_180','d181_365','d365_plus']) k),
                       'band_value_paise', (
                           SELECT jsonb_object_agg(k, COALESCE(
                               (SELECT f.value_paise FROM final f
                                 WHERE f.item_id = n.item_id AND f.band = k), 0))
                             FROM unnest(ARRAY['d0_30','d31_60','d61_90',
                                               'd91_180','d181_365','d365_plus']) k))
                   ORDER BY lower(n.name), n.item_id)
              FROM named n), '[]'::jsonb),
        'total_qty_by_band', (
            SELECT jsonb_object_agg(k, COALESCE(
                (SELECT SUM(f.qty)::text FROM final f WHERE f.band = k), '0'))
              FROM unnest(ARRAY['d0_30','d31_60','d61_90',
                                'd91_180','d181_365','d365_plus']) k),
        'total_value_by_band', (
            SELECT jsonb_object_agg(k, COALESCE(
                (SELECT SUM(f.value_paise) FROM final f WHERE f.band = k), 0))
              FROM unnest(ARRAY['d0_30','d31_60','d61_90',
                                'd91_180','d181_365','d365_plus']) k),
        -- Ties to the Inventory control account: the same Σ value_delta_paise
        -- migration 363 reports, summed from the deltas rather than from the
        -- rounded band shares.
        'total_value_paise', COALESCE((SELECT SUM(n.value_paise) FROM named n), 0),
        'total_items',       COALESCE((SELECT COUNT(*) FROM named n), 0)
    )) INTO v_out;

    RETURN v_out;
END
$fn$;

COMMENT ON FUNCTION public.stock_ageing_as_at(uuid, uuid, date, uuid) IS
    'Stock ageing as at a date: the units ON HAND bucketed by how long they '
    'have been held, first-in-first-out, with the item''s own carrying amount '
    'split across the bands in proportion to quantity (largest remainder, so '
    'it foots). FIFO whatever the client''s AS-2 paragraph 14 cost formula is — '
    'this is a physical question about the godown, not a cost assignment, and '
    'nothing here reads inventory_costing_method. The bands are a reporting '
    'convention: Schedule III prescribes ageing for trade receivables and '
    'payables only. One row per item, per CLAUDE.md''s reporting rule. '
    'domain/reporting/stock_ageing.py is the identical rule for mock mode and '
    'the two are pinned by tests/test_stock_ageing_parity_pg.py. Migration 408.';

REVOKE EXECUTE ON FUNCTION public.stock_ageing_as_at(uuid, uuid, date, uuid) FROM PUBLIC;
REVOKE EXECUTE ON FUNCTION public.stock_ageing_as_at(uuid, uuid, date, uuid) FROM anon;
GRANT EXECUTE ON FUNCTION public.stock_ageing_as_at(uuid, uuid, date, uuid)
    TO authenticated, service_role;

COMMIT;
