-- Migration 179 — Firm HSN/SAC Library (HSN/SAC architecture redesign, Phase 2)
--
-- Architecture decision (see docs/HSN_SAC_REDESIGN.md for the full review):
-- Caflow does not expose a shared HSN/SAC master to users. Each firm owns and
-- curates its own HSN/SAC library; every Product/Service and every invoice
-- line selects its code from THIS table, never from `public.hsn_master`.
--
-- `public.hsn_master` (migrations 036/175/178) is retained UNCHANGED as an
-- internal, non-exposed implementation detail: it powers server-side
-- search-assist when a CA is adding a code to their own library (so they
-- don't have to already know the exact digits/title), and nothing else. Its
-- rows are never returned to the invoice-line picker and never bulk-exported.
-- This table — not hsn_master — is the only HSN/SAC source surfaced to users.
--
-- Firm-scoped, one row per (firm_id, hsn_code). CA-owned: added by import
-- (Excel/CSV via onboarding or the library page) or manual entry, edited,
-- retired (never hard-deleted — `is_active`), with audit metadata.
--
-- The GST rate stored here is a CA-entered PRE-FILL HINT ONLY (CGST Rule
-- 46(g)) — never used in any tax or journal computation. Products/Services
-- and invoice lines snapshot their own values; nothing joins back to this
-- table for financial output, so editing/retiring a code here can never
-- alter a previously raised invoice, GSTR-1 return or PDF (same safety
-- argument as hsn_master — see docs/HSN_SAC_MASTER_MAINTENANCE.md).

CREATE TABLE IF NOT EXISTS public.firm_hsn_library (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id        UUID        NOT NULL,
    hsn_code       TEXT        NOT NULL,
    description    TEXT        NOT NULL,
    hsn_type       TEXT        NOT NULL CHECK (hsn_type IN ('goods', 'services')),
    gst_rate_pct   NUMERIC(5,2),                      -- CA-entered hint; NULL = not set / varies
    uqc            TEXT,                               -- optional unit-quantity code
    notes          TEXT,                               -- optional CA note (e.g. notification reference)
    source         TEXT        NOT NULL DEFAULT 'manual' CHECK (source IN ('manual', 'import')),
    is_active      BOOLEAN     NOT NULL DEFAULT true,   -- retire, don't delete
    created_by     UUID,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_by     UUID,
    updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT firm_hsn_library_rate_range
        CHECK (gst_rate_pct IS NULL OR (gst_rate_pct >= 0 AND gst_rate_pct <= 100))
);

-- One code per firm. A firm re-adding a retired code updates it back to
-- active rather than creating a duplicate row (enforced at the app layer).
CREATE UNIQUE INDEX IF NOT EXISTS uq_firm_hsn_library_code
    ON public.firm_hsn_library (firm_id, hsn_code);

-- Search/listing read path.
CREATE INDEX IF NOT EXISTS idx_firm_hsn_library_active
    ON public.firm_hsn_library (firm_id, is_active, hsn_code);

ALTER TABLE public.firm_hsn_library ENABLE ROW LEVEL SECURITY;

-- RLS: firm isolation, mirroring the service_catalogue pattern (migration 176).
-- Service-role bypasses RLS, so the router also firm-scopes every query.
DROP POLICY IF EXISTS firm_hsn_library_isolation ON public.firm_hsn_library;
CREATE POLICY firm_hsn_library_isolation
    ON public.firm_hsn_library
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id())
    WITH CHECK (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE ON public.firm_hsn_library TO authenticated;
GRANT ALL                     ON public.firm_hsn_library TO service_role;
