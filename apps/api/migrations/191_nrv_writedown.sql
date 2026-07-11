-- Migration 191 — Lower-of-cost-or-NRV write-down movement type
--
-- AS-2 / Ind AS 2 / ICDS-II require inventory to be carried at the LOWER of
-- cost or net realisable value; if NRV drops below the recorded moving-
-- average cost, the difference must be written down and expensed. Adds a
-- distinct movement_type for this — a value-only event (quantity never
-- changes) — rather than overloading the existing 'adjustment' type, which
-- always represents a quantity change (physical count, damage, theft, etc.).

ALTER TABLE public.inventory_stock_ledger
    DROP CONSTRAINT IF EXISTS inventory_stock_ledger_movement_type_check;
ALTER TABLE public.inventory_stock_ledger
    ADD CONSTRAINT inventory_stock_ledger_movement_type_check
        CHECK (movement_type IN
            ('opening', 'purchase', 'sale', 'sale_reversal', 'purchase_reversal',
             'adjustment', 'sale_return', 'purchase_return', 'nrv_writedown'));
