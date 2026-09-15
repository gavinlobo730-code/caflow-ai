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

-- THE CHECK GOES BACK TO MIGRATION 191's LIST, AND ONLY IF NO TRANSFER WAS
-- EVER RECORDED. Narrowing a CHECK is not additive: a row already written as
-- 'transfer' would make the ADD CONSTRAINT fail and take the whole rollback
-- with it. Refusing with a sentence is better than a rollback that dies
-- halfway — the same shape as 392's refusal to drop a table with an
-- outstanding s.143 clock on it.
DO $$
DECLARE n bigint;
BEGIN
  SELECT count(*) INTO n FROM public.inventory_stock_ledger
   WHERE movement_type = 'transfer';
  IF n > 0 THEN
    RAISE EXCEPTION 'Refusing to roll back 398: % stock ledger row(s) record a '
      'godown transfer. Narrowing movement_type would reject them, and '
      'deleting them would silently move that stock back to where it was not.',
      n;
  END IF;
END $$;

ALTER TABLE public.inventory_stock_ledger
  DROP CONSTRAINT IF EXISTS inventory_stock_ledger_movement_type_check;
ALTER TABLE public.inventory_stock_ledger
  ADD CONSTRAINT inventory_stock_ledger_movement_type_check
    CHECK (movement_type IN
      ('opening', 'purchase', 'sale', 'sale_reversal', 'purchase_reversal',
       'adjustment', 'sale_return', 'purchase_return', 'nrv_writedown'));

ALTER TABLE public.inventory_stock_ledger DROP COLUMN IF EXISTS batch_id;
ALTER TABLE public.inventory_stock_ledger DROP COLUMN IF EXISTS godown_id;

DROP TABLE IF EXISTS public.inventory_batches;
DROP TABLE IF EXISTS public.godowns;

COMMIT;
