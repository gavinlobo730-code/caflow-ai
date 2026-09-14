-- Rollback for 394 — which cost formula prices a stock issue (INV-02).
--
-- REFUSES while any movement was priced on FIFO. Dropping
-- `inventory_stock_ledger.costing_method` does not re-cost anything — the
-- `value_delta_paise` those rows carry is what the COGS journal already
-- posted, and it stays — but it destroys the only record of WHICH formula
-- produced it. AS-5 paragraph 32 requires the effect of a change in
-- accounting policy to be disclosed, and after this the ledger could not say
-- that a change had happened at all, let alone when.
--
-- `clients.inventory_costing_method` comes off with it: with no stamp on the
-- ledger, a policy on the client would describe books nothing corroborates.
--
-- To roll back deliberately: put the affected clients back on the weighted
-- average and re-cost their movements — which is itself a change in
-- accounting policy needing disclosure — then run this.

BEGIN;

DO $$
DECLARE n BIGINT;
BEGIN
  SELECT count(*) INTO n FROM public.inventory_stock_ledger
   WHERE costing_method = 'fifo';
  IF n > 0 THEN
    RAISE EXCEPTION
      'Refusing to roll back 394: % stock movement(s) were priced on FIFO. '
      'Dropping the stamp destroys the only record of which cost formula '
      'produced their value, which AS-5 paragraph 32 requires to be '
      'disclosable. Re-cost those clients first.', n;
  END IF;
END $$;

DROP INDEX IF EXISTS public.idx_inventory_stock_ledger_fifo;
ALTER TABLE public.inventory_stock_ledger
  DROP CONSTRAINT IF EXISTS inventory_stock_ledger_costing_method_check;
ALTER TABLE public.inventory_stock_ledger DROP COLUMN IF EXISTS costing_method;
ALTER TABLE public.clients
  DROP CONSTRAINT IF EXISTS clients_inventory_costing_method_check;
ALTER TABLE public.clients DROP COLUMN IF EXISTS inventory_costing_method;

COMMIT;
