-- Migration 115: Engagement Letter Management System
--
-- These tables support ENGAGEMENT LETTERS (PDF documents sent to clients for signing).
-- This is DISTINCT from fee_engagements (the table used by the existing engagements.py
-- router, which tracks ongoing service engagements and fee arrangements).
--
-- engagement_templates — reusable letter templates with HTML content and {{merge_fields}}
-- engagements          — individual engagement letter instances with full lifecycle tracking
-- engagement_events    — immutable audit trail of every status transition on an engagement
--
-- All monetary values are stored in integer paise (₹1 = 100 paise) — never float.
-- CGST Act Section 31 requires fee documentation before service commencement.

-- ── engagement_templates ──────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.engagement_templates (
    id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id      UUID        NOT NULL,
    name         TEXT        NOT NULL,
    service_type TEXT        NOT NULL,
    content      TEXT        NOT NULL DEFAULT '',  -- HTML with {{merge_fields}}
    version      INTEGER     NOT NULL DEFAULT 1,
    is_default   BOOLEAN     NOT NULL DEFAULT false,
    is_deleted   BOOLEAN     NOT NULL DEFAULT false,
    created_by   UUID        NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── engagements (engagement LETTERS — not fee_engagements) ───────────────────

CREATE TABLE IF NOT EXISTS public.engagements (
    id                 UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id            UUID        NOT NULL,
    lead_id            UUID        NULL,
    client_id          UUID        NULL,
    template_id        UUID        NULL,
    engagement_number  TEXT        NOT NULL,
    title              TEXT        NOT NULL,
    status             TEXT        NOT NULL DEFAULT 'Draft'
                           CHECK (status IN (
                               'Draft', 'Generated', 'Sent', 'Viewed',
                               'Signed', 'Rejected', 'Expired'
                           )),
    content            TEXT        NOT NULL DEFAULT '',
    fee_amount_paise   BIGINT      NOT NULL DEFAULT 0,
    start_date         DATE        NULL,
    expiry_date        DATE        NULL,
    recipient_name     TEXT        NULL,
    recipient_email    TEXT        NULL,
    generated_pdf_url  TEXT        NULL,
    signed_pdf_url     TEXT        NULL,
    sent_at            TIMESTAMPTZ NULL,
    viewed_at          TIMESTAMPTZ NULL,
    signed_at          TIMESTAMPTZ NULL,
    rejected_at        TIMESTAMPTZ NULL,
    rejection_notes    TEXT        NULL,
    created_by         UUID        NULL,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── engagement_events (audit trail of every status transition) ────────────────

CREATE TABLE IF NOT EXISTS public.engagement_events (
    id             UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
    engagement_id  UUID        NOT NULL,
    firm_id        UUID        NOT NULL,
    event_type     TEXT        NOT NULL,
    user_id        UUID        NULL,
    metadata       JSONB       NULL,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ── Indexes ───────────────────────────────────────────────────────────────────

-- Active templates by firm (most common list query)
CREATE INDEX IF NOT EXISTS idx_engagement_templates_firm
    ON public.engagement_templates (firm_id)
    WHERE is_deleted = false;

-- Engagement letters by firm, status, and recency
CREATE INDEX IF NOT EXISTS idx_engagements_firm_status
    ON public.engagements (firm_id, status, created_at DESC);

-- Engagement letters linked to a specific lead
CREATE INDEX IF NOT EXISTS idx_engagements_lead
    ON public.engagements (lead_id)
    WHERE lead_id IS NOT NULL;

-- Engagement letters linked to a specific client
CREATE INDEX IF NOT EXISTS idx_engagements_client
    ON public.engagements (client_id)
    WHERE client_id IS NOT NULL;

-- Audit trail in chronological order per engagement
CREATE INDEX IF NOT EXISTS idx_engagement_events_engagement
    ON public.engagement_events (engagement_id, created_at DESC);
