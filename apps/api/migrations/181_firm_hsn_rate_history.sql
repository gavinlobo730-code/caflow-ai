-- Migration 181 — Firm HSN/SAC Rate History (HSN/SAC architecture redesign,
-- Decision D)
--
-- Architecture decision: GST rates change by GST Council decision / CBIC
-- notification (e.g. the 22-Sep-2025 "GST 2.0" rationalization), so a single
-- flat rate on a library entry goes silently stale the moment the Council
-- moves. This table lets a CA record that history explicitly, per code, per
-- effective date range — WITHOUT Caflow becoming a tax-determination engine:
--
--   - Every row is CA-ENTERED. Caflow ships no seed data and asserts no
--     Caflow-authoritative rate for any code (mirrors Decision A: Caflow
--     does not own tax classification/rate content).
--   - Resolution (given a code + as-of date, find the applicable row) is a
--     PRE-FILL HINT for the product/invoice-line form ONLY — never applied
--     to tax/journal math automatically. The CA always confirms; the
--     invoice line snapshots its own gst_rate_bps exactly as today.
--   - No automatic slab/cess/RCM branching logic. Value-slab-dependent or
--     buyer-dependent rates are the CA's judgement call, recorded as
--     separate rows with a note — Caflow does not attempt to compute which
--     applies to a given transaction (that would cross into tax
--     determination, which Decision D explicitly rejects).
--   - Historical invoices are unaffected either way: they already snapshot
--     their own hsn_sac + gst_rate_bps and never join this table.

CREATE TABLE IF NOT EXISTS public.firm_hsn_rate_history (
    id                    UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id               UUID        NOT NULL,
    firm_hsn_library_id   UUID        NOT NULL
        REFERENCES public.firm_hsn_library(id) ON DELETE CASCADE,
    gst_rate_pct          NUMERIC(5,2) NOT NULL,   -- CA-entered, not Caflow-computed
    cess_rate_pct         NUMERIC(5,2),            -- optional ad-valorem compensation cess
    cess_specific_paise_per_unit BIGINT,           -- optional specific cess (integer paise/unit)
    supply_type           TEXT        NOT NULL DEFAULT 'taxable'
        CHECK (supply_type IN ('taxable', 'exempt', 'nil', 'non_gst')),
    effective_from        DATE        NOT NULL,
    effective_to          DATE,                     -- NULL = currently in effect
    notes                 TEXT,                     -- e.g. "Notification 09/2025-CTR, GST 2.0"
    created_by            UUID,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT firm_hsn_rate_history_rate_range
        CHECK (gst_rate_pct >= 0 AND gst_rate_pct <= 100),
    CONSTRAINT firm_hsn_rate_history_cess_range
        CHECK (cess_rate_pct IS NULL OR (cess_rate_pct >= 0 AND cess_rate_pct <= 100)),
    CONSTRAINT firm_hsn_rate_history_cess_specific_nonneg
        CHECK (cess_specific_paise_per_unit IS NULL OR cess_specific_paise_per_unit >= 0),
    CONSTRAINT firm_hsn_rate_history_date_order
        CHECK (effective_to IS NULL OR effective_to >= effective_from)
);

-- Resolution read path: "which rate applies to code X as of date D" queries
-- filter by (firm_hsn_library_id) then order by effective_from desc.
CREATE INDEX IF NOT EXISTS idx_firm_hsn_rate_history_lookup
    ON public.firm_hsn_rate_history (firm_hsn_library_id, effective_from DESC);

ALTER TABLE public.firm_hsn_rate_history ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS firm_hsn_rate_history_isolation ON public.firm_hsn_rate_history;
CREATE POLICY firm_hsn_rate_history_isolation
    ON public.firm_hsn_rate_history
    FOR ALL TO authenticated
    USING (firm_id = get_my_firm_id())
    WITH CHECK (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE ON public.firm_hsn_rate_history TO authenticated;
GRANT ALL                     ON public.firm_hsn_rate_history TO service_role;
