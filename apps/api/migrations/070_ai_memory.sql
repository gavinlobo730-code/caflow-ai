-- Phase 13: AI Memory & Compounding Intelligence
-- Idempotent — safe to run multiple times

-- ── Client Profiles (semantic memory) ────────────────────────────
CREATE TABLE IF NOT EXISTS client_profiles (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                 UUID NOT NULL,
    client_id               UUID NOT NULL,
    profile_version         INTEGER NOT NULL DEFAULT 1,

    -- Behavioural profile
    doc_upload_reliability  NUMERIC(5,2) DEFAULT 0,   -- 0-100 score
    portal_engagement       NUMERIC(5,2) DEFAULT 0,
    avg_response_time_days  NUMERIC(6,2),
    preferred_contact       TEXT DEFAULT 'email',

    -- Compliance history
    avg_gst_delay_days      NUMERIC(6,2),
    avg_tds_delay_days      NUMERIC(6,2),
    missed_deadline_count   INTEGER NOT NULL DEFAULT 0,
    notice_count            INTEGER NOT NULL DEFAULT 0,
    compliance_score        NUMERIC(5,2) DEFAULT 75,

    -- Financial patterns
    seasonal_revenue_peak   TEXT,              -- "Q3", "Mar", etc.
    cash_flow_risk_months   JSONB DEFAULT '[]', -- ["January","March"]
    avg_debtor_days         NUMERIC(6,2),

    -- Recurring issues (array of issue codes)
    recurring_issues        JSONB DEFAULT '[]',

    -- Year-end patterns
    avg_year_end_duration_days INTEGER,
    common_provisions       JSONB DEFAULT '[]',
    common_auditor_requests JSONB DEFAULT '[]',

    -- Meta
    last_computed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    data_points_used        INTEGER NOT NULL DEFAULT 0,
    is_current              BOOLEAN NOT NULL DEFAULT true,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- REPLAYABILITY FIX: client_profiles already exists from migration 059, so the
-- CREATE TABLE above is a silent no-op and the indexes below bind to columns
-- that the 059-era table never had. On a clean replay this file died here with:
-- column "is_current" does not exist. Same reasoning as the 068 repair.
ALTER TABLE client_profiles ADD COLUMN IF NOT EXISTS firm_id           UUID;
ALTER TABLE client_profiles ADD COLUMN IF NOT EXISTS client_id         UUID;
ALTER TABLE client_profiles ADD COLUMN IF NOT EXISTS is_current        BOOLEAN NOT NULL DEFAULT true;
ALTER TABLE client_profiles ADD COLUMN IF NOT EXISTS last_computed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE INDEX IF NOT EXISTS idx_cp_firm_client    ON client_profiles(firm_id, client_id);
CREATE INDEX IF NOT EXISTS idx_cp_current        ON client_profiles(firm_id, is_current) WHERE is_current = true;
CREATE INDEX IF NOT EXISTS idx_cp_computed       ON client_profiles(last_computed_at);

-- ── Client Profile History ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS client_profile_history (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL,
    client_id       UUID NOT NULL,
    profile_id      UUID NOT NULL REFERENCES client_profiles(id) ON DELETE CASCADE,
    profile_version INTEGER NOT NULL,
    snapshot        JSONB NOT NULL DEFAULT '{}',
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cph_client ON client_profile_history(firm_id, client_id, computed_at DESC);

-- ── Firm Profiles ─────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS firm_profiles (
    id                          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id                     UUID NOT NULL UNIQUE,

    -- Operational intelligence
    peak_workload_months        JSONB DEFAULT '[]',
    avg_tasks_per_client        NUMERIC(6,2),
    common_bottleneck_types     JSONB DEFAULT '[]',
    team_utilisation_trend      TEXT DEFAULT 'stable',

    -- Portfolio intelligence
    portfolio_compliance_score  NUMERIC(5,2) DEFAULT 75,
    common_risk_categories      JSONB DEFAULT '[]',
    portfolio_health_trend      TEXT DEFAULT 'stable',

    -- Revenue intelligence
    avg_revenue_per_client_paise BIGINT DEFAULT 0,
    revenue_growth_trend        TEXT DEFAULT 'stable',
    billing_recovery_rate       NUMERIC(5,2) DEFAULT 85,

    -- Seasonal intelligence
    deadline_concentration      JSONB DEFAULT '{}',   -- month -> count
    capacity_risk_months        JSONB DEFAULT '[]',

    last_computed_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    is_current                  BOOLEAN NOT NULL DEFAULT true,
    created_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_fp_firm ON firm_profiles(firm_id);

-- ── AI Memory Triggers ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_memory_triggers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL,
    client_id       UUID,
    trigger_type    TEXT NOT NULL,  -- repeat_issue|deadline_at_risk|cash_flow_warning|year_end_readiness|pattern_anomaly

    -- Evidence
    title           TEXT NOT NULL,
    what_detected   TEXT NOT NULL,
    evidence        JSONB NOT NULL DEFAULT '[]',   -- array of evidence data points
    why_it_matters  TEXT NOT NULL,
    recommended_action TEXT NOT NULL,

    -- Scoring
    confidence      NUMERIC(5,2) NOT NULL DEFAULT 0,  -- 0-100
    severity        TEXT NOT NULL DEFAULT 'medium',    -- low|medium|high|critical

    -- Lifecycle
    status          TEXT NOT NULL DEFAULT 'active',    -- active|acknowledged|resolved|dismissed
    acknowledged_by UUID,
    acknowledged_at TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,

    -- Source
    source_data     JSONB DEFAULT '{}',
    profile_version INTEGER,

    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_amt_firm        ON ai_memory_triggers(firm_id, status);
CREATE INDEX IF NOT EXISTS idx_amt_client      ON ai_memory_triggers(client_id, trigger_type);
CREATE INDEX IF NOT EXISTS idx_amt_type        ON ai_memory_triggers(firm_id, trigger_type, status);
CREATE INDEX IF NOT EXISTS idx_amt_created     ON ai_memory_triggers(created_at DESC);

-- ── Pattern Anomalies ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS pattern_anomalies (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL,
    client_id       UUID,
    anomaly_type    TEXT NOT NULL,   -- purchase_spike|expense_drop|unusual_compliance|workflow_anomaly
    metric_name     TEXT NOT NULL,
    baseline_value  NUMERIC(14,2),
    actual_value    NUMERIC(14,2),
    deviation_pct   NUMERIC(8,2),
    deviation_score NUMERIC(6,2),   -- sigma / standard deviations
    period          TEXT NOT NULL,  -- "2026-Q1", "2026-04"
    explanation     TEXT,
    evidence        JSONB DEFAULT '[]',
    status          TEXT NOT NULL DEFAULT 'open',  -- open|reviewed|false_positive|actioned
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_pa_firm   ON pattern_anomalies(firm_id, status);
CREATE INDEX IF NOT EXISTS idx_pa_client ON pattern_anomalies(client_id);

-- ── Year-End Planning Reports ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS year_end_reports (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID NOT NULL,
    client_id           UUID NOT NULL,
    financial_year      TEXT NOT NULL,  -- "2025-26"

    prior_year_lessons  JSONB DEFAULT '[]',
    recurring_provisions JSONB DEFAULT '[]',
    auditor_requests    JSONB DEFAULT '[]',
    historical_bottlenecks JSONB DEFAULT '[]',
    planning_recommendations JSONB DEFAULT '[]',

    ai_narrative        TEXT,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    status              TEXT NOT NULL DEFAULT 'draft'  -- draft|shared|acknowledged
);

CREATE INDEX IF NOT EXISTS idx_yer_firm   ON year_end_reports(firm_id);
CREATE INDEX IF NOT EXISTS idx_yer_client ON year_end_reports(client_id, financial_year);
