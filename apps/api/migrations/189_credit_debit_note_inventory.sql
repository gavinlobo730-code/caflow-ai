-- Migration 189 — Credit Note / Debit Note inventory wiring (audit fix)
--
-- Migration 188 built the moving-average costing engine and wired it into
-- sales invoices and purchase bills, but credit notes (sales returns) and
-- debit notes (purchase returns) had no catalogue link at all — a CA
-- processing a sales or purchase return today sees NO stock impact
-- whatsoever. Found during the post-completion inventory-module audit
-- (CLAUDE.md: "audit it after completion and complete anything missing").
--
-- Adds the same service_catalogue_id link purchase_bill_lines got in 188,
-- this time on credit_note_lines and debit_note_lines, and widens the
-- inventory_stock_ledger.movement_type CHECK to admit the two new movement
-- kinds a return needs: 'sale_return' (goods physically come back into
-- stock on a credit note) and 'purchase_return' (goods physically leave
-- stock on a debit note). source_type on inventory_stock_ledger already
-- documented 'credit_note' | 'debit_note' as valid values (188's own
-- column comment) — this migration is what actually makes them usable.

ALTER TABLE public.credit_note_lines
    ADD COLUMN IF NOT EXISTS service_catalogue_id UUID REFERENCES public.service_catalogue(id) ON DELETE SET NULL;

ALTER TABLE public.debit_note_lines
    ADD COLUMN IF NOT EXISTS service_catalogue_id UUID REFERENCES public.service_catalogue(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_credit_note_lines_service_catalogue
    ON public.credit_note_lines (service_catalogue_id) WHERE service_catalogue_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_debit_note_lines_service_catalogue
    ON public.debit_note_lines (service_catalogue_id) WHERE service_catalogue_id IS NOT NULL;

ALTER TABLE public.inventory_stock_ledger
    DROP CONSTRAINT IF EXISTS inventory_stock_ledger_movement_type_check;
ALTER TABLE public.inventory_stock_ledger
    ADD CONSTRAINT inventory_stock_ledger_movement_type_check
        CHECK (movement_type IN
            ('opening', 'purchase', 'sale', 'sale_reversal', 'purchase_reversal',
             'adjustment', 'sale_return', 'purchase_return'));
