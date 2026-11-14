-- Migration 588: the stock register reads each item's latest stock-ledger row in the database, one row per item (ledger POST-A-435).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- The stock register shows each item's quantity, average cost and value from its LATEST row in inventory_stock_ledger (the running
-- totals every new movement chains from). `routers/inventory._last_ledger_rows` found those rows by paging the client's movements newest
-- first, with an IN list that shrank as items were found, and stopped after eight pages of a thousand. Each page finds the items among
-- its rows, so it ran out only when page after page was filled by ONE busy item each: with eight items that each had a thousand
-- movements more recent than the next, every item older than those (slow stock at a busy trading client) was not reached, and the
-- register rendered it as ZERO quantity and ZERO value, with a log line only. The answer is one row per item, so the question belongs
-- where the rows are.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
--  * `public.stock_latest_rows(p_firm, p_client, p_items uuid[]) RETURNS jsonb`: ONE value, an array holding, for each item asked
--    for, its latest row of this firm and client (a set of rows would be cut at PostgREST's db-max-rows, silently), by
--    `created_at` descending and then `id` descending (the same order `_last_ledger_row` chains from, so the register shows the row the
--    next movement will cost from). An item with no movement is absent, which the register shows as nothing received. One probe per
--    item through the index below, so the cost is the size of the register, not of the history.
--  * `idx_inventory_stock_ledger_item_latest (service_catalogue_id, created_at DESC, id DESC)`: what each probe reads.
--  * SECURITY INVOKER; EXECUTE is revoked from PUBLIC, anon and authenticated and given to service_role alone: the API calls it on its
--    privileged client after asserting the caller's access to the client, naming the firm and the client itself.
-- No table, column or policy changes. Mock twin: `domain/inventory/latest_rows.latest_rows`, held to it by a parity test.

BEGIN;

CREATE INDEX IF NOT EXISTS idx_inventory_stock_ledger_item_latest
    ON public.inventory_stock_ledger (service_catalogue_id, created_at DESC, id DESC);

CREATE OR REPLACE FUNCTION public.stock_latest_rows(
    p_firm   uuid,
    p_client uuid,
    p_items  uuid[]
) RETURNS jsonb
LANGUAGE sql STABLE SECURITY INVOKER
SET search_path = public, pg_catalog
AS $fn$
    -- ONE jsonb value and not a set of rows: PostgREST cuts a set-returning call at db-max-rows without a word (migration 265
    -- measured it at 1,000 of 3,531), and the 1,001st item would be shown at zero, which is the defect this function ends.
    SELECT COALESCE(jsonb_agg(jsonb_build_object(
               'service_catalogue_id',   latest.service_catalogue_id,
               'running_qty_units',      latest.running_qty_units,
               'running_avg_cost_paise', latest.running_avg_cost_paise,
               'running_value_paise',    latest.running_value_paise)
             ORDER BY latest.service_catalogue_id), '[]'::jsonb)
      FROM (SELECT DISTINCT unnest(p_items) AS item_id) AS asked
      CROSS JOIN LATERAL (
          SELECT l.service_catalogue_id, l.running_qty_units, l.running_avg_cost_paise, l.running_value_paise
            FROM public.inventory_stock_ledger AS l
           WHERE l.service_catalogue_id = asked.item_id
             AND l.firm_id = p_firm
             AND l.client_id = p_client
           ORDER BY l.created_at DESC, l.id DESC
           LIMIT 1
      ) AS latest;
$fn$;

COMMENT ON FUNCTION public.stock_latest_rows(uuid, uuid, uuid[]) IS
  'Each asked item''s latest stock-ledger row of this firm and client (created_at DESC, id DESC): the running totals the stock register '
  'shows and the next movement chains from. Mock twin: domain/inventory/latest_rows.latest_rows (POST-A-435, migration 588).';

REVOKE ALL ON FUNCTION public.stock_latest_rows(uuid, uuid, uuid[]) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.stock_latest_rows(uuid, uuid, uuid[]) TO service_role;

COMMIT;
