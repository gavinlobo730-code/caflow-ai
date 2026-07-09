-- Migration 182 — Products & Services become client-owned (HSN/SAC workflow
-- alignment: "Client Products & Services (Not Shared)")
--
-- Product/Service master data belongs to the CLIENT, not the firm: "Client B
-- must never inherit Client A's products." `service_catalogue` (migration
-- 176, broadened in 180) was firm-scoped only — every client of a firm
-- shared one list. This migration adds the missing client dimension.
--
-- service_catalogue predates this decision and has no production data (MVP
-- Phase 1, pre-launch) — existing rows are cleared rather than migrated so
-- client_id can be a clean NOT NULL column from the start, matching every
-- other client-owned table in this schema (client_sales_invoices,
-- purchase_bills, hsn_sac_preferences, …). Nothing to backfill.

DELETE FROM public.service_catalogue;

ALTER TABLE public.service_catalogue
    ADD COLUMN client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE;

-- Replace the firm-only duplicate-name guard with a firm+client one: the
-- same product/service name is allowed once per CLIENT, not once per firm —
-- Client A and Client B may each have their own "Consulting Retainer".
DROP INDEX IF EXISTS uq_service_catalogue_active_name;
CREATE UNIQUE INDEX uq_service_catalogue_active_name
    ON public.service_catalogue (firm_id, client_id, lower(regexp_replace(btrim(name), '\s+', ' ', 'g')))
    WHERE is_active;

-- Ranking read path is now per-client.
DROP INDEX IF EXISTS idx_service_catalogue_rank;
CREATE INDEX idx_service_catalogue_rank
    ON public.service_catalogue (firm_id, client_id, last_used_at DESC, use_count DESC);

-- RLS: identical three-policy stack used by hsn_sac_preferences (migration
-- 101) / invoice_deliveries / receipts (migration 084 assignment-scoped
-- pattern) — firm scope, then client-assignment scope, then the
-- internal-practice-client restriction.
DROP POLICY IF EXISTS firm_service_catalogue ON public.service_catalogue;
CREATE POLICY firm_service_catalogue
    ON public.service_catalogue
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id());

CREATE POLICY service_catalogue_assignment_scope
    ON public.service_catalogue
    AS RESTRICTIVE
    FOR ALL TO authenticated
    USING (can_access_client((client_id)::text));

CREATE POLICY service_catalogue_internal_partner_only
    ON public.service_catalogue
    AS RESTRICTIVE
    FOR ALL TO authenticated
    USING (
        (get_my_role() = 'Partner'::text)
        OR ((client_id)::text IS DISTINCT FROM (my_internal_client_id())::text)
    );

COMMENT ON TABLE public.service_catalogue IS
    'Client-owned Product & Service master (goods + services). Name is the '
    'only mandatory field. HSN/SAC must come from firm_hsn_library (the '
    'firm-wide shared library — app-enforced, no DB FK). Snapshot-source '
    'only — invoice lines copy values, never reference this table, so '
    'editing/archiving a row never changes a past invoice. Deliberately '
    'excludes stock/valuation/quantity/SKU/barcode/warehouse. Scoped to one '
    'client — never shared across a firm''s clients (migration 182).';
