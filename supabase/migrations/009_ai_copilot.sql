-- Phase 11: AI Copilot Platform
-- Idempotent — safe to run multiple times

-- ── AI Conversations ─────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_conversations (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL,
    user_id         UUID NOT NULL,
    title           TEXT NOT NULL DEFAULT 'New Conversation',
    context_type    TEXT NOT NULL DEFAULT 'global',  -- global|client|compliance|workflow|executive
    context_id      UUID,  -- client_id, workflow_id etc depending on context_type
    message_count   INTEGER NOT NULL DEFAULT 0,
    last_message_at TIMESTAMPTZ,
    is_archived     BOOLEAN NOT NULL DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_conv_firm ON ai_conversations(firm_id, is_archived);
CREATE INDEX IF NOT EXISTS idx_ai_conv_user ON ai_conversations(user_id);

-- ── AI Messages ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL,
    role            TEXT NOT NULL,  -- user|assistant|system
    content         TEXT NOT NULL,
    tokens_used     INTEGER,
    model_used      TEXT DEFAULT 'llama-3.3-70b-versatile',
    metadata        JSONB DEFAULT '{}',  -- cited_sources, suggested_actions, etc.
    feedback_rating INTEGER,  -- 1-5 stars, null if not rated
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_messages_conv ON ai_messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_ai_messages_firm ON ai_messages(firm_id);

-- ── AI Context Windows ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_context_windows (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES ai_conversations(id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL,
    context_data    JSONB NOT NULL DEFAULT '{}',  -- injected context snapshot
    token_estimate  INTEGER,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_ctx_conv ON ai_context_windows(conversation_id);

-- ── AI Summaries ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_summaries (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL,
    summary_type    TEXT NOT NULL,  -- client|compliance|workflow|executive|relationship
    entity_id       UUID,           -- client_id, workflow_template_id, etc.
    title           TEXT NOT NULL,
    content         TEXT NOT NULL,
    key_points      JSONB DEFAULT '[]',
    metadata        JSONB DEFAULT '{}',
    model_used      TEXT DEFAULT 'llama-3.3-70b-versatile',
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,
    is_stale        BOOLEAN NOT NULL DEFAULT false
);

CREATE INDEX IF NOT EXISTS idx_ai_summaries_firm ON ai_summaries(firm_id, summary_type);
CREATE INDEX IF NOT EXISTS idx_ai_summaries_entity ON ai_summaries(entity_id);
CREATE INDEX IF NOT EXISTS idx_ai_summaries_stale ON ai_summaries(is_stale, expires_at);

-- ── AI Recommendations ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_recommendations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id             UUID NOT NULL,
    client_id           UUID,
    recommendation_type TEXT NOT NULL,  -- risk|opportunity|compliance|workflow|relationship|health
    priority            TEXT NOT NULL DEFAULT 'medium',  -- critical|high|medium|low
    title               TEXT NOT NULL,
    description         TEXT NOT NULL,
    rationale           TEXT,
    action_label        TEXT,  -- e.g., "Review Now", "Create Task"
    action_data         JSONB DEFAULT '{}',
    status              TEXT NOT NULL DEFAULT 'pending',  -- pending|accepted|dismissed|snoozed
    snoozed_until       TIMESTAMPTZ,
    acted_by            UUID,
    acted_at            TIMESTAMPTZ,
    model_used          TEXT DEFAULT 'llama-3.3-70b-versatile',
    source_context      JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_recs_firm ON ai_recommendations(firm_id, status);
CREATE INDEX IF NOT EXISTS idx_ai_recs_client ON ai_recommendations(client_id);
CREATE INDEX IF NOT EXISTS idx_ai_recs_priority ON ai_recommendations(firm_id, priority, status);

-- ── AI Actions (triggered by AI) ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_actions (
    id                UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id           UUID NOT NULL,
    recommendation_id UUID REFERENCES ai_recommendations(id),
    action_type       TEXT NOT NULL,  -- create_task|send_notification|trigger_workflow|create_alert
    action_data       JSONB NOT NULL DEFAULT '{}',
    status            TEXT NOT NULL DEFAULT 'pending',  -- pending|executed|failed|cancelled
    executed_by       UUID,  -- user who confirmed, or null for autonomous
    executed_at       TIMESTAMPTZ,
    result_data       JSONB,
    error_message     TEXT,
    created_at        TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_actions_firm ON ai_actions(firm_id, status);

-- ── AI Feedback ──────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS ai_feedback (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id     UUID NOT NULL,
    message_id  UUID REFERENCES ai_messages(id) ON DELETE CASCADE,
    user_id     UUID NOT NULL,
    rating      INTEGER NOT NULL CHECK (rating BETWEEN 1 AND 5),
    feedback_text TEXT,
    tags        JSONB DEFAULT '[]',  -- ["helpful","accurate","too_long"]
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_ai_feedback_firm ON ai_feedback(firm_id);
CREATE INDEX IF NOT EXISTS idx_ai_feedback_message ON ai_feedback(message_id);
