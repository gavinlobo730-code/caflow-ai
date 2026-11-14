-- Rollback of migration 588: drop the latest-row function and its index. Nothing else was changed, so nothing else is undone. Safe to
-- run twice. The API before this migration does not call the function.

DROP FUNCTION IF EXISTS public.stock_latest_rows(uuid, uuid, uuid[]);
DROP INDEX IF EXISTS public.idx_inventory_stock_ledger_item_latest;
