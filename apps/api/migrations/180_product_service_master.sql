-- Migration 180 — Product & Service master (HSN/SAC architecture redesign, Phase 3)
--
-- Broadens `service_catalogue` (migration 176, services-only billing presets)
-- into a minimal Product & Service master covering goods too. Extended in
-- place rather than replaced with a new table: the existing columns already
-- cover Name/Description/HSN/GST-rate/Price/Unit, so this stays one table
-- with one HSN wiring path (avoids the duplicate-HSN-logic anti-pattern of
-- running a second, parallel goods catalogue alongside the services one).
--
-- Still deliberately NOT an inventory/items master: no stock, valuation,
-- quantity-on-hand, SKU, barcode, or warehouse linkage. Migration 176's lock
-- on those fields stands. If a future change tries to add any of them, it
-- must be stopped and re-scoped.
--
-- Only `name` is mandatory (unchanged); every new column here is optional.
-- `hsn_sac` must reference a code in the firm's OWN `firm_hsn_library`
-- (migration 179) — enforced at the application layer, not a DB foreign key:
-- this table follows the same no-hard-FK-on-tax-fields convention as
-- invoice lines and the original service_catalogue design, so a firm
-- retiring a library code can never break an existing product/service row,
-- and an existing row's price/rate/HSN always stays exactly what was
-- selected (snapshot-on-pick semantics unchanged: picking a row still
-- copies its values onto the invoice line, never links to it).

ALTER TABLE public.service_catalogue
    ADD COLUMN IF NOT EXISTS kind TEXT NOT NULL DEFAULT 'service' CHECK (kind IN ('good', 'service'));

ALTER TABLE public.service_catalogue
    ADD COLUMN IF NOT EXISTS purchase_price_paise BIGINT;      -- optional; integer paise (money rule)

ALTER TABLE public.service_catalogue
    ADD COLUMN IF NOT EXISTS category TEXT;                     -- optional, free-text grouping

ALTER TABLE public.service_catalogue
    ADD CONSTRAINT service_catalogue_purchase_price_nonneg
        CHECK (purchase_price_paise IS NULL OR purchase_price_paise >= 0);

COMMENT ON TABLE public.service_catalogue IS
    'Firm-scoped Product & Service master (goods + services). Name is the only '
    'mandatory field. HSN/SAC must come from firm_hsn_library (app-enforced, no '
    'DB FK). Snapshot-source only — invoice lines copy values, never reference '
    'this table, so editing/archiving a row never changes a past invoice. '
    'Deliberately excludes stock/valuation/quantity/SKU/barcode/warehouse.';
