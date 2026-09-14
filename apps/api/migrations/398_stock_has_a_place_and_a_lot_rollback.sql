-- Rollback for 398.
--
-- REFUSES while any stock movement names a godown or a batch. Those columns
-- are the only record of where the stock is and which lot it came from, and
-- the movements themselves carry journal entries that cannot be deleted
-- (migration 251). Dropping the tables would leave a per-location position
-- nobody could reconstruct and, on a client whose goods expire, no record of
-- what is in date.
BEGIN;

DO $$
DECLARE n INTEGER;
BEGIN
  SELECT count(*) INTO n FROM public.inventory_stock_ledger
   WHERE godown_id IS NOT NULL OR batch_id IS NOT NULL;
  IF n > 0 THEN
    RAISE EXCEPTION
      'Refusing to roll back 398: % stock movements name a godown or a batch. '
      'Those columns are the only record of where the stock is and which lot '
      'it came from.', n;
  END IF;
END $$;

DROP FUNCTION IF EXISTS public.stock_position_detail_as_at(uuid, uuid, date, uuid);

ALTER TABLE public.inventory_stock_ledger DROP COLUMN IF EXISTS batch_id;
ALTER TABLE public.inventory_stock_ledger DROP COLUMN IF EXISTS godown_id;

DROP TABLE IF EXISTS public.inventory_batches;
DROP TABLE IF EXISTS public.godowns;

COMMIT;
