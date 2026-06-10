-- Migration 052: Phase 3 Compliance — Government Notices, GSTR-2B, Form 26AS
-- All monetary values in integer paise — CGST Act Section 145A
-- RLS isolates data per firm using get_my_firm_id()

-- ─── 1. Government Notices ───────────────────────────────────────────────────
-- Extracted from uploaded PDFs/images via AI document intelligence

CREATE TABLE IF NOT EXISTS public.government_notices (
    id                  UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID        NOT NULL,
    client_id           UUID        NOT NULL,
    notice_type         TEXT        NOT NULL,  -- 'gst_scrutiny', 'income_tax', 'mca_show_cause', etc.
    authority           TEXT        NOT NULL,  -- 'GSTN', 'Income Tax Dept', 'MCA21', etc.
    reference_no        TEXT,
    issue_date          DATE,
    response_due_date   DATE,
    description         TEXT,
    source_document_url TEXT,                  -- uploaded file URL
    extracted_data      JSONB,                 -- raw AI extraction result
    status              TEXT        NOT NULL DEFAULT 'open',  -- open, in_progress, responded, closed
    task_id             UUID,                  -- linked work task
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.government_notices ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_isolation" ON public.government_notices
    USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.government_notices TO authenticated;

-- ─── 2. GSTR-2B Uploads ──────────────────────────────────────────────────────
-- CGST Act Section 38 — auto-drafted inward supplies statement

CREATE TABLE IF NOT EXISTS public.gstr2b_uploads (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                 UUID        NOT NULL,
    client_id               UUID        NOT NULL,
    period                  TEXT        NOT NULL,  -- MMYYYY e.g. '042025'
    uploaded_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    file_url                TEXT,
    raw_data                JSONB,
    reconciliation_result   JSONB,
    status                  TEXT        NOT NULL DEFAULT 'uploaded',  -- uploaded, reconciled
    created_by              UUID
);

ALTER TABLE public.gstr2b_uploads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_isolation" ON public.gstr2b_uploads
    USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.gstr2b_uploads TO authenticated;

-- ─── 3. Form 26AS Uploads ────────────────────────────────────────────────────
-- IT Act Section 203AA — Annual TDS/TCS Statement

CREATE TABLE IF NOT EXISTS public.form_26as_uploads (
    id                      UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                 UUID        NOT NULL,
    client_id               UUID        NOT NULL,
    financial_year          TEXT        NOT NULL,  -- e.g. '2025-26'
    uploaded_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    file_url                TEXT,
    raw_data                JSONB,
    reconciliation_result   JSONB,
    status                  TEXT        NOT NULL DEFAULT 'uploaded',
    created_by              UUID
);

ALTER TABLE public.form_26as_uploads ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_isolation" ON public.form_26as_uploads
    USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.form_26as_uploads TO authenticated;
