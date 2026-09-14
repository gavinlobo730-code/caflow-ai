-- 394 — which cost formula prices a stock issue (INV-02).
--
-- WHAT WAS WRONG
--     `domain/inventory_service.py` priced every issue at the MOVING AVERAGE
--     and had no other answer. AS-2 paragraph 14 permits the cost of
--     inventories to be assigned using the FIRST-IN, FIRST-OUT or the WEIGHTED
--     AVERAGE cost formula, and a practice's clients use both — FIFO is
--     ordinary in trading and in anything with a shelf life, and is what a
--     client migrating from Tally commonly arrives with.
--
--     A client whose books are kept on FIFO and whose software can only do
--     weighted average has a closing stock figure, and therefore a PROFIT,
--     that its own accounting policy note does not describe.
--
-- TWO COLUMNS, AND THE SECOND IS THE ONE THAT MATTERS
--     `clients.inventory_costing_method` is the POLICY. AS-2 paragraph 16
--     requires the same formula for all inventories of a similar nature and
--     use, so it belongs to the client and not to a receipt, and no caller
--     may pass one per movement.
--
--     `inventory_stock_ledger.costing_method` records which formula actually
--     priced THAT row. That is what makes a change of policy visible: AS-5
--     paragraph 29 permits the change and paragraph 32 requires its EFFECT to
--     be disclosed, so the period it took effect from has to be derivable from
--     the ledger rather than remembered. It also means a row priced under the
--     old formula is never mistaken for one priced under the new.
--
-- NULL IS NOT A DEFAULT DRESSED UP AS ONE
--     Every client's books in this product HAVE been kept on the weighted
--     average, because it was the only formula there was. So NULL on the
--     client records that nobody has CHOSEN, and the engine's answer for a
--     NULL — weighted average — is a fact about how the books were actually
--     kept rather than a guess. There is deliberately NO backfill of either
--     column and no DEFAULT on the client's: a default would make the choice
--     look made.
--
--     The LEDGER column does carry a default, and for the opposite reason:
--     every row already in it was priced on the moving average, and a NULL
--     there would be unreadable rather than honest. It is backfilled to
--     'moving_average' for exactly that reason — the value is known.
--
-- NOTHING IS RE-COSTED, EVER
--     A change of formula is PROSPECTIVE. Re-costing history would move a
--     closing stock figure that is already in a filed return and a signed
--     balance sheet, and AS-5 paragraph 32 asks for the effect of a change to
--     be disclosed — not for software to restate the past quietly.
--     `domain/inventory/costing.switch_refusal` is where that is decided, and
--     `effective_from` is required there rather than being a column here,
--     because the ledger's own stamp IS the record of when it changed.
--
-- WHAT IS NOT HERE
--     Standard cost. AS-2 paragraph 17 allows it only where the results
--     approximate actual cost and requires the standards to be regularly
--     reviewed — two judgements no ledger holds — and it needs a variance
--     account and a revision cycle to mean anything. Named in the domain
--     module rather than half-built.

ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS inventory_costing_method TEXT;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.clients'::regclass
       AND conname = 'clients_inventory_costing_method_check') THEN
    ALTER TABLE public.clients
      ADD CONSTRAINT clients_inventory_costing_method_check
      CHECK (inventory_costing_method IS NULL
             OR inventory_costing_method IN ('moving_average', 'fifo'));
  END IF;
END $$;

ALTER TABLE public.inventory_stock_ledger
  ADD COLUMN IF NOT EXISTS costing_method TEXT NOT NULL DEFAULT 'moving_average';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.inventory_stock_ledger'::regclass
       AND conname = 'inventory_stock_ledger_costing_method_check') THEN
    ALTER TABLE public.inventory_stock_ledger
      ADD CONSTRAINT inventory_stock_ledger_costing_method_check
      CHECK (costing_method IN ('moving_average', 'fifo'));
  END IF;
END $$;

-- The one query that has to be fast: "which formula priced this item's
-- movements, and did it change". Partial, because only the FIFO rows are
-- interesting — the default is the other one.
CREATE INDEX IF NOT EXISTS idx_inventory_stock_ledger_fifo
  ON public.inventory_stock_ledger (service_catalogue_id, movement_date)
  WHERE costing_method = 'fifo';

COMMENT ON COLUMN public.clients.inventory_costing_method IS
  'AS-2 paragraph 14''s cost formula for this client''s inventories: '
  '''moving_average'' or ''fifo''. AS-2 paragraph 16 requires the SAME formula '
  'for all inventories of a similar nature and use, which is why it lives here '
  'and not on a receipt. NULL means nobody has chosen — and the engine answers '
  'weighted average for a NULL because that is how these books were ACTUALLY '
  'kept, it being the only formula the product had. No default and no '
  'backfill: a default would make the choice look made.';
COMMENT ON COLUMN public.inventory_stock_ledger.costing_method IS
  'Which formula priced THIS movement. AS-5 paragraph 29 permits a change of '
  'accounting policy and paragraph 32 requires its effect to be disclosed, so '
  'the period a change took effect from must be derivable from the ledger '
  'rather than remembered — and a row priced under the old formula must never '
  'be mistaken for one priced under the new. Defaulted and backfilled to '
  '''moving_average'' because every row already here was priced that way: the '
  'value is KNOWN, unlike the client''s own unchosen policy.';
