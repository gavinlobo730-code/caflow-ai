-- Migration 176 — Service Catalogue (Sales-Invoice Batch 6)
--
-- A reusable, SERVICES-ONLY billing preset system: a CA firm stores the services
-- it repeatedly bills ("GST filing — ₹5,000 @18%, SAC 998231") so the invoice
-- editor can drop a fully pre-priced line in one pick.
--
-- THIS IS NOT AN INVENTORY / ITEMS MASTER (locked product decision, Blueprint
-- roadmap Batch 8). There is deliberately NO stock, NO valuation, NO quantity
-- on hand, NO purchase/warehouse linkage — only the billing defaults below. If a
-- future change tries to add any of those, it must be stopped and re-scoped.
--
-- Firm-scoped: presets are shared across all of a firm's clients (unlike the
-- client-scoped hsn_sac_preferences learning table). A preset is a CONVENIENCE
-- SNAPSHOT SOURCE only: picking one copies its values onto the invoice line, so
-- editing or archiving a preset later NEVER changes a past invoice (invoice lines
-- store their own description/HSN/rate/amount as free text — no FK to this table).
--
-- The stored GST rate + price are PRE-FILL HINTS (CGST Rule 46(g)); they are
-- never read by any tax, journal or report code — only by the picker/list UI.

CREATE TABLE IF NOT EXISTS public.service_catalogue (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id            UUID        NOT NULL,
    name               TEXT        NOT NULL,          -- e.g. "Statutory Audit"
    description        TEXT,                          -- default invoice-line text (falls back to name)
    hsn_sac            TEXT,                          -- default SAC/HSN (optional; free-text on the line)
    gst_rate_bps       INTEGER,                       -- default GST rate in bps (1800 = 18%); hint only
    default_rate_paise BIGINT      NOT NULL DEFAULT 0,-- default unit price in integer paise (money rule)
    unit               TEXT,                          -- optional UQC / unit label
    notes              TEXT,                          -- optional internal note
    is_active          BOOLEAN     NOT NULL DEFAULT true,  -- archive = is_active false (never hard-deleted)
    use_count          INTEGER     NOT NULL DEFAULT 0,     -- picks so far (drives "frequently used")
    last_used_at       TIMESTAMPTZ,                        -- last pick (drives "recent")
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT service_catalogue_gst_rate_bps_range
        CHECK (gst_rate_bps IS NULL OR (gst_rate_bps >= 0 AND gst_rate_bps <= 10000)),
    CONSTRAINT service_catalogue_rate_nonneg
        CHECK (default_rate_paise >= 0)
);

-- Duplicate prevention: no two ACTIVE presets may share a name within a firm
-- (case/space-insensitive). An archived namesake may coexist, so archiving then
-- re-creating the same name is allowed.
-- Normalisation matches the router's _norm_name (lower + collapse whitespace),
-- so the DB backstop and the app-level duplicate guard agree exactly.
CREATE UNIQUE INDEX IF NOT EXISTS uq_service_catalogue_active_name
    ON public.service_catalogue (firm_id, lower(regexp_replace(btrim(name), '\s+', ' ', 'g')))
    WHERE is_active;

-- Ranking read path: firm's presets ordered recency-then-frequency.
CREATE INDEX IF NOT EXISTS idx_service_catalogue_rank
    ON public.service_catalogue (firm_id, last_used_at DESC, use_count DESC);

ALTER TABLE public.service_catalogue ENABLE ROW LEVEL SECURITY;

-- RLS: firm isolation (service-role bypasses RLS, so the router also firm-scopes
-- every query — matching the customers/hsn_sac_preferences pattern).
DROP POLICY IF EXISTS firm_service_catalogue ON public.service_catalogue;
CREATE POLICY firm_service_catalogue
    ON public.service_catalogue
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE ON public.service_catalogue TO authenticated;
GRANT ALL                     ON public.service_catalogue TO service_role;
