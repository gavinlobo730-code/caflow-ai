-- Migration 188 — Inventory costing module
--
-- Migrations 176/180 explicitly locked service_catalogue as "NOT an
-- inventory/items master — no stock, valuation, quantity-on-hand." This
-- migration is the deliberate, explicit product decision that supersedes
-- that lock: goods items in the catalogue now carry real stock quantity and
-- moving-average cost. Services are entirely unaffected — every column here
-- is meaningless (and left NULL/0) for kind='service' rows.
--
-- Design:
--   * service_catalogue gains the CURRENT stock state (qty on hand, moving-
--     average cost) as cached/denormalised fields — same pattern as
--     client_sales_invoices.total_paise being cached rather than recomputed
--     from lines on every read. inventory_stock_ledger below is the
--     authoritative audit trail; these two columns are always derivable
--     from summing it, kept in sync transactionally by the app layer.
--   * inventory_stock_ledger is an append-only movement log: every stock
--     in/out (opening balance, purchase, sale, adjustment) is one row, with
--     the running qty/cost/value AFTER that movement captured on the row
--     itself — so a point-in-time stock ledger view (mirrors the accounting
--     Ledger view) never needs to replay history.
--   * purchase_bill_lines gets the same service_catalogue_id link sales
--     invoice lines already have (migration 184) — required so a purchase
--     bill line can be identified as "restocking this product" for the
--     moving-average recompute. Purchase bills had NO catalogue link before
--     this; ServiceCataloguePicker will be wired into the Purchase Bill line
--     editor for goods only, matching the sales invoice pattern.
--   * All money is integer paise (CLAUDE.md). Quantity is NUMERIC(10,3),
--     matching the existing invoice/bill line quantity columns.

ALTER TABLE public.service_catalogue
    ADD COLUMN IF NOT EXISTS opening_qty_units NUMERIC(10,3),
    ADD COLUMN IF NOT EXISTS opening_cost_paise BIGINT,
    ADD COLUMN IF NOT EXISTS stock_qty_units NUMERIC(10,3) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS avg_cost_paise BIGINT NOT NULL DEFAULT 0;

ALTER TABLE public.service_catalogue
    ADD CONSTRAINT service_catalogue_opening_cost_nonneg
        CHECK (opening_cost_paise IS NULL OR opening_cost_paise >= 0),
    ADD CONSTRAINT service_catalogue_avg_cost_nonneg
        CHECK (avg_cost_paise >= 0);

COMMENT ON COLUMN public.service_catalogue.stock_qty_units IS
    'Current on-hand quantity for kind=good items only — cached running total, authoritative source is inventory_stock_ledger. Always 0 for services.';
COMMENT ON COLUMN public.service_catalogue.avg_cost_paise IS
    'Current moving-average cost per unit (integer paise) for kind=good items only. Always 0 for services.';

CREATE TABLE IF NOT EXISTS public.inventory_stock_ledger (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
    client_id           UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
    service_catalogue_id UUID NOT NULL REFERENCES public.service_catalogue(id) ON DELETE CASCADE,
    movement_date       DATE NOT NULL,
    movement_type       TEXT NOT NULL CHECK (movement_type IN
                            ('opening', 'purchase', 'sale', 'sale_reversal', 'purchase_reversal', 'adjustment')),
    quantity_delta      NUMERIC(10,3) NOT NULL,        -- positive = stock in, negative = stock out
    unit_cost_paise     BIGINT NOT NULL,                -- cost/unit applied to THIS movement (integer paise)
    value_delta_paise   BIGINT NOT NULL,                -- signed; quantity_delta's value at unit_cost_paise
    running_qty_units   NUMERIC(10,3) NOT NULL,          -- qty on hand AFTER this movement
    running_avg_cost_paise BIGINT NOT NULL,               -- moving-average cost/unit AFTER this movement
    running_value_paise BIGINT NOT NULL,                 -- running_qty_units * running_avg_cost_paise
    source_type         TEXT,                            -- 'sales_invoice' | 'purchase_bill' | 'credit_note' | 'debit_note' | 'adjustment' | NULL for opening
    source_id            UUID,
    reference_no         TEXT,
    journal_entry_id     UUID,                           -- COGS/Inventory journal entry, if one was posted for this movement
    notes                TEXT,
    created_by            UUID,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_inventory_stock_ledger_item
    ON public.inventory_stock_ledger (service_catalogue_id, movement_date, created_at);
CREATE INDEX IF NOT EXISTS idx_inventory_stock_ledger_source
    ON public.inventory_stock_ledger (source_type, source_id) WHERE source_id IS NOT NULL;

ALTER TABLE public.inventory_stock_ledger ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_inventory_stock_ledger" ON public.inventory_stock_ledger
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.inventory_stock_ledger TO authenticated;

COMMENT ON TABLE public.inventory_stock_ledger IS
    'Append-only stock movement audit trail (moving-average costing). Never updated or deleted after insert — a correction is a new adjustment row, same as the journal ledger never rewrites history.';

-- Purchase bill lines had no product/service link at all (migration 184's own
-- comment: "ServiceCataloguePicker is not wired into Purchase Bill... lines").
-- Required now so a bill line can be identified as restocking a specific
-- product. Same nullable / SET NULL / traceability-only semantics as 184.
ALTER TABLE public.purchase_bill_lines
    ADD COLUMN IF NOT EXISTS service_catalogue_id UUID REFERENCES public.service_catalogue(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_purchase_bill_lines_service_catalogue
    ON public.purchase_bill_lines (service_catalogue_id)
    WHERE service_catalogue_id IS NOT NULL;
