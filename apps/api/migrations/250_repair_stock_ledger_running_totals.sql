-- Migration 250: repair the inventory stock ledger's running totals, neutralise
-- the correction-marker rows, and stamp reversal flags that were left behind.
--
-- Found by an integrity audit. None of this affected the General Ledger — the
-- financial statements were correct throughout. What was wrong is the stock
-- ledger's own derived columns and one bookkeeping flag.
--
-- 1. Running totals had drifted (303 of 315 items)
-- --------------------------------------------------
-- domain/inventory_service.py maintains running_qty_units / running_value_paise
-- / running_avg_cost_paise as the accumulation of each item's own movements. It
-- is written to hold one invariant, stated in _compute_stock_out:
--
--     "With this, the deltas always sum to the running value."
--
-- That invariant had broken for all but 12 items. The GL was never affected:
-- SUM(value_delta_paise) over the REAL movements (purchase / purchase_reversal
-- / sale) equals the Inventory control account to the paise. Only the derived
-- running_* columns had drifted, so anything reading per-item stock value could
-- show a wrong figure while the Balance Sheet stayed right.
--
-- This rebuilds them as the running sum of each item's own deltas, ordered the
-- way the service chains movements (movement_date, created_at, id), and
-- re-derives average cost exactly as _round_paise does: ROUND_HALF_UP(value /
-- qty), and 0 once quantity is exhausted (the service's force-close rule).
--
-- 2. Correction markers carried a delta they should not have
-- ----------------------------------------------------------
-- A previous audit inserted 'adjustment' rows to correct drifted running totals.
-- They were given a non-zero quantity_delta / value_delta_paise recording the
-- SIZE of the correction, which is self-defeating in a ledger whose running
-- totals are the sum of its deltas: it moved SUM(delta) away from the GL by the
-- same amount. Their own note is explicit that no GL journal was posted because
-- the General Ledger was never wrong, and their running_* equals the sum of the
-- item's real movements — which is what reconciles to the GL.
--
-- Both legs are zeroed (value alone would leave quantity and value incoherent).
-- The rows are KEPT, with their explanatory note, as the audit trail. Only rows
-- with no journal_entry_id are touched: an adjustment backed by a real journal
-- is a genuine stock movement and must not be neutralised.
--
-- 3. Reversed originals left unflagged
-- -------------------------------------
-- An entry that has a reversal on the books must carry is_reversed = true, or
-- _create_journal's idempotency fast-path can still match it. One entry had a
-- valid reversal but the flag was never flipped. This is the narrow FALSE->TRUE
-- flip the immutability triggers permit on a posted row (migration 213).
--
-- Safety: idempotent (a second run finds nothing to change), self-targeting
-- rather than keyed to specific ids, and guarded by post-conditions that abort
-- if any invariant is still violated afterwards.

BEGIN;

-- ── 1. Neutralise the correction markers (must precede the rebuild, so the
--       rebuild accumulates the corrected deltas). ────────────────────────────
UPDATE public.inventory_stock_ledger
   SET quantity_delta    = 0,
       value_delta_paise = 0
 WHERE movement_type = 'adjustment'
   AND journal_entry_id IS NULL
   AND (quantity_delta <> 0 OR value_delta_paise <> 0);

-- ── 2. Rebuild every row's running totals from its item's own deltas. ────────
WITH ordered AS (
    SELECT id,
           sum(quantity_delta)    OVER w AS run_qty,
           sum(value_delta_paise) OVER w AS run_val
      FROM public.inventory_stock_ledger
    WINDOW w AS (PARTITION BY service_catalogue_id
                 ORDER BY movement_date, created_at, id
                 ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
)
UPDATE public.inventory_stock_ledger l
   SET running_qty_units      = o.run_qty,
       running_value_paise    = o.run_val,
       running_avg_cost_paise = CASE WHEN o.run_qty > 0
                                     THEN round(o.run_val::numeric / o.run_qty)::bigint
                                     ELSE 0 END
  FROM ordered o
 WHERE l.id = o.id
   AND (l.running_qty_units   IS DISTINCT FROM o.run_qty
     OR l.running_value_paise IS DISTINCT FROM o.run_val
     OR l.running_avg_cost_paise IS DISTINCT FROM
        CASE WHEN o.run_qty > 0
             THEN round(o.run_val::numeric / o.run_qty)::bigint ELSE 0 END);

-- ── 3. Stamp any original that already has a reversal on the books. ──────────
UPDATE public.journal_entries o
   SET is_reversed = true
 WHERE NOT o.is_reversed
   AND o.deleted_at IS NULL
   AND EXISTS (SELECT 1 FROM public.journal_entries r
                WHERE r.reversal_of = o.id AND r.deleted_at IS NULL);

-- ── Post-conditions ─────────────────────────────────────────────────────────
DO $verify$
DECLARE
    v_drifted   int;
    v_markers   int;
    v_flags     int;
    v_avg       int;
BEGIN
    -- Every item's last row must equal the sum of that item's deltas.
    WITH per_item AS (
        SELECT service_catalogue_id,
               sum(quantity_delta) AS q, sum(value_delta_paise) AS v
          FROM public.inventory_stock_ledger
         GROUP BY service_catalogue_id
    ),
    last_row AS (
        SELECT DISTINCT ON (service_catalogue_id)
               service_catalogue_id, running_qty_units AS rq, running_value_paise AS rv
          FROM public.inventory_stock_ledger
         ORDER BY service_catalogue_id, movement_date DESC, created_at DESC, id DESC
    )
    SELECT count(*) INTO v_drifted
      FROM per_item p JOIN last_row l USING (service_catalogue_id)
     WHERE l.rq <> p.q OR l.rv <> p.v;

    IF v_drifted > 0 THEN
        RAISE EXCEPTION
            'Migration 250 failed: % item(s) still have running totals that '
            'disagree with the sum of their own movements', v_drifted;
    END IF;

    SELECT count(*) INTO v_markers
      FROM public.inventory_stock_ledger
     WHERE movement_type = 'adjustment' AND journal_entry_id IS NULL
       AND (quantity_delta <> 0 OR value_delta_paise <> 0);
    IF v_markers > 0 THEN
        RAISE EXCEPTION 'Migration 250 failed: % correction marker(s) still carry a delta', v_markers;
    END IF;

    SELECT count(*) INTO v_avg
      FROM public.inventory_stock_ledger
     WHERE running_avg_cost_paise <> CASE WHEN running_qty_units > 0
             THEN round(running_value_paise::numeric / running_qty_units)::bigint
             ELSE 0 END;
    IF v_avg > 0 THEN
        RAISE EXCEPTION 'Migration 250 failed: % row(s) have an inconsistent average cost', v_avg;
    END IF;

    SELECT count(*) INTO v_flags
      FROM public.journal_entries o
     WHERE NOT o.is_reversed AND o.deleted_at IS NULL
       AND EXISTS (SELECT 1 FROM public.journal_entries r
                    WHERE r.reversal_of = o.id AND r.deleted_at IS NULL);
    IF v_flags > 0 THEN
        RAISE EXCEPTION 'Migration 250 failed: % reversed entr(ies) still unflagged', v_flags;
    END IF;
END
$verify$;

COMMIT;
