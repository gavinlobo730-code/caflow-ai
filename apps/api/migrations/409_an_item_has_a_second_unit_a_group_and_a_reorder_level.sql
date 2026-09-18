-- ============================================================================
-- 409 — an item is stocked in one unit, transacted in another, and reordered
--       at a level somebody chose
--
-- WHY
--     INV-03 and INV-09 each deferred the alternate unit to the other, so
--     neither built it. A wholesaler buys cement in tonnes and sells it in
--     bags; a stationer buys pens in boxes of twelve and sells them singly.
--     `service_catalogue` carries ONE `unit`, so the CA either re-types a
--     converted quantity onto every line or keeps two catalogue rows for one
--     physical item — at which point the on-hand figure is split across two
--     rows and ties to nothing.
--
--     And there was no reorder level at all, so the one question a stock
--     master exists to answer between counts — what do I need to buy — had to
--     be answered by reading the register item by item. `category` has been a
--     free-text grouping since migration 180 and nothing has ever grouped by
--     it, which is why this migration adds no column for the item GROUP: the
--     column was always there, the report was not.
--
-- THE LEDGER NEVER LEARNS THAT A SECOND UNIT EXISTS
--     `inventory_stock_ledger` holds `quantity_delta` and a running total and
--     `stock_position_as_at` sums the deltas, so a movement recorded in either
--     unit would add boxes to pieces. The conversion happens at the DOOR —
--     `domain/inventory/units.to_primary` — and nothing stores a quantity in
--     the alternate unit. That is the same discipline migration 398 took about
--     a batch: a column that COULD change what is stored is the one that
--     eventually does.
--
-- NOTHING IS BACK-FILLED AND ALL THREE COLUMNS ARE NULLABLE WITH NO DEFAULT
--     An absent alternate unit is the state every existing row is in and is
--     correct for the large majority of items for ever. An absent reorder
--     level is NOT zero: zero is a real answer ("tell me when it runs out"),
--     so defaulting would silently record a decision nobody made and park
--     every item in the "above" bucket. `domain/inventory/reorder` reports the
--     absence as its own state.
--
-- THE FACTOR'S NAME POINTS
--     `units_per_alternate` rather than `conversion_factor`, because the
--     second name does not say which way it goes and a factor applied upside
--     down is a 144x error on a box of twelve that still looks like a
--     plausible quantity.
--
-- Additive and idempotent. No data changes and no figure moves.
-- ============================================================================

ALTER TABLE public.service_catalogue
    ADD COLUMN IF NOT EXISTS alternate_unit       TEXT,
    ADD COLUMN IF NOT EXISTS units_per_alternate  NUMERIC(10,3),
    ADD COLUMN IF NOT EXISTS reorder_level_units  NUMERIC(10,3);

DO $$ BEGIN
  -- Strictly positive. Zero would make every alternate quantity nil and a
  -- negative one would reverse the movement.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'service_catalogue_units_per_alternate_positive') THEN
    ALTER TABLE public.service_catalogue
      ADD CONSTRAINT service_catalogue_units_per_alternate_positive
      CHECK (units_per_alternate IS NULL OR units_per_alternate > 0);
  END IF;

  -- Both or neither. A unit with no factor cannot be converted and a factor
  -- with no unit converts to nothing; either alone is a half-recorded fact
  -- that reads as a whole one on a screen.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'service_catalogue_alternate_unit_pairs') THEN
    ALTER TABLE public.service_catalogue
      ADD CONSTRAINT service_catalogue_alternate_unit_pairs
      CHECK ((alternate_unit IS NULL) = (units_per_alternate IS NULL));
  END IF;

  -- An item whose two units are the same has one unit. Stored, the pair would
  -- invite a later factor edit that silently rescales the master.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'service_catalogue_alternate_unit_differs') THEN
    ALTER TABLE public.service_catalogue
      ADD CONSTRAINT service_catalogue_alternate_unit_differs
      CHECK (alternate_unit IS NULL OR unit IS NULL
             OR upper(btrim(alternate_unit)) <> upper(btrim(unit)));
  END IF;

  -- A negative reorder level is not a level. Zero is allowed and is a real
  -- answer; see the header.
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conname = 'service_catalogue_reorder_level_nonneg') THEN
    ALTER TABLE public.service_catalogue
      ADD CONSTRAINT service_catalogue_reorder_level_nonneg
      CHECK (reorder_level_units IS NULL OR reorder_level_units >= 0);
  END IF;
END $$;

COMMENT ON COLUMN public.service_catalogue.alternate_unit IS
  'A second UQC the item may be bought or sold in. The STOCK LEDGER is always '
  'kept in `unit`; a quantity typed in this one is converted at the door by '
  'domain/inventory/units.to_primary and nothing stores a quantity in it. '
  'NULL means the item has one unit, which is the state of every row before '
  'migration 409 and the right answer for most items for ever.';

COMMENT ON COLUMN public.service_catalogue.units_per_alternate IS
  'How many `unit` make ONE `alternate_unit` — a box of twelve pens whose unit '
  'is PCS stores 12. Named for the direction because a factor applied upside '
  'down is a 144x error that still looks like a plausible quantity. Paired '
  'with alternate_unit by CHECK: both or neither.';

COMMENT ON COLUMN public.service_catalogue.reorder_level_units IS
  'The on-hand quantity at or below which this item should be reordered. '
  'NULL is NOT zero — zero is a real answer meaning "tell me when it runs '
  'out", so an absent level is reported by domain/inventory/reorder as its '
  'own state rather than parking the item in the "above" bucket. No default '
  'and no backfill for exactly that reason.';
