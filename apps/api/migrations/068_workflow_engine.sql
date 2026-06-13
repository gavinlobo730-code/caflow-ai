-- Phase 10: Workflow Automation Engine
-- Idempotent — safe to run multiple times

-- ── Workflow Templates ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_templates (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL,
    name            TEXT NOT NULL,
    description     TEXT,
    category        TEXT NOT NULL DEFAULT 'general',  -- onboarding|compliance|accounting|payroll|gst|tds|mca|income_tax|lifecycle|health|relationship
    trigger_type    TEXT NOT NULL,                     -- see trigger enum below
    trigger_config  JSONB NOT NULL DEFAULT '{}',
    conditions      JSONB NOT NULL DEFAULT '[]',       -- nested condition tree
    is_active       BOOLEAN NOT NULL DEFAULT true,
    is_system       BOOLEAN NOT NULL DEFAULT false,    -- built-in vs firm-created
    version         INTEGER NOT NULL DEFAULT 1,
    execution_count INTEGER NOT NULL DEFAULT 0,
    success_count   INTEGER NOT NULL DEFAULT 0,
    failure_count   INTEGER NOT NULL DEFAULT 0,
    avg_duration_ms INTEGER,
    created_by      UUID,
    updated_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_templates_firm ON workflow_templates(firm_id);
CREATE INDEX IF NOT EXISTS idx_wf_templates_active ON workflow_templates(firm_id, is_active);
CREATE INDEX IF NOT EXISTS idx_wf_templates_trigger ON workflow_templates(trigger_type);

-- ── Workflow Steps ───────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_steps (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id UUID NOT NULL REFERENCES workflow_templates(id) ON DELETE CASCADE,
    step_order  INTEGER NOT NULL,
    step_type   TEXT NOT NULL,  -- trigger|condition|action|approval|delay|branch
    name        TEXT NOT NULL,
    description TEXT,
    config      JSONB NOT NULL DEFAULT '{}',
    next_step_id        UUID,   -- for linear flows
    true_branch_step_id  UUID,  -- for branch/condition steps
    false_branch_step_id UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_steps_template ON workflow_steps(template_id);

-- ── Workflow Triggers ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_triggers (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    template_id     UUID NOT NULL REFERENCES workflow_templates(id) ON DELETE CASCADE,
    trigger_type    TEXT NOT NULL,
    trigger_config  JSONB NOT NULL DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_triggers_template ON workflow_triggers(template_id);
CREATE INDEX IF NOT EXISTS idx_wf_triggers_type ON workflow_triggers(trigger_type, is_active);

-- ── Workflow Conditions ──────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_conditions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    step_id         UUID NOT NULL REFERENCES workflow_steps(id) ON DELETE CASCADE,
    condition_group TEXT NOT NULL DEFAULT 'AND',  -- AND|OR
    field           TEXT NOT NULL,
    operator        TEXT NOT NULL,  -- >|<|=|>=|<=|contains|equals|starts_with|before|after|within_days
    value           TEXT NOT NULL,
    value_type      TEXT NOT NULL DEFAULT 'string',  -- string|number|date|boolean
    parent_id       UUID,  -- for nested conditions
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_conditions_step ON workflow_conditions(step_id);

-- ── Workflow Instances ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_instances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL,
    template_id     UUID NOT NULL REFERENCES workflow_templates(id),
    client_id       UUID,
    trigger_event   TEXT NOT NULL,
    trigger_data    JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|running|completed|failed|cancelled|waiting_approval
    current_step_id UUID,
    context_data    JSONB NOT NULL DEFAULT '{}',      -- runtime variables
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    failed_at       TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_instances_firm ON workflow_instances(firm_id);
CREATE INDEX IF NOT EXISTS idx_wf_instances_template ON workflow_instances(template_id);
CREATE INDEX IF NOT EXISTS idx_wf_instances_client ON workflow_instances(client_id);
CREATE INDEX IF NOT EXISTS idx_wf_instances_status ON workflow_instances(firm_id, status);

-- ── Workflow Action Logs ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_action_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id UUID NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
    step_id     UUID,
    step_name   TEXT,
    action_type TEXT NOT NULL,
    action_config JSONB NOT NULL DEFAULT '{}',
    status      TEXT NOT NULL DEFAULT 'pending',  -- pending|running|success|failed|skipped
    started_at  TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    duration_ms INTEGER,
    result_data JSONB,
    error_message TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_action_logs_instance ON workflow_action_logs(instance_id);
CREATE INDEX IF NOT EXISTS idx_wf_action_logs_status ON workflow_action_logs(status);

-- ── Workflow Executions (Audit Trail) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_executions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id UUID NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
    firm_id     UUID NOT NULL,
    event_type  TEXT NOT NULL,  -- started|step_completed|step_failed|completed|failed|cancelled|approval_requested|approved|rejected
    event_data  JSONB NOT NULL DEFAULT '{}',
    actor_id    UUID,
    actor_type  TEXT DEFAULT 'system',  -- system|user
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_executions_instance ON workflow_executions(instance_id);
CREATE INDEX IF NOT EXISTS idx_wf_executions_firm ON workflow_executions(firm_id);

-- ── Workflow Failures ────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_failures (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id UUID NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
    firm_id     UUID NOT NULL,
    step_id     UUID,
    step_name   TEXT,
    error_type  TEXT NOT NULL,
    error_message TEXT NOT NULL,
    error_data  JSONB,
    retry_count INTEGER NOT NULL DEFAULT 0,
    resolved    BOOLEAN NOT NULL DEFAULT false,
    resolved_at TIMESTAMPTZ,
    resolved_by UUID,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_failures_firm ON workflow_failures(firm_id, resolved);
CREATE INDEX IF NOT EXISTS idx_wf_failures_instance ON workflow_failures(instance_id);

-- ── Workflow Approvals ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_approvals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id     UUID NOT NULL REFERENCES workflow_instances(id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL,
    step_id         UUID,
    step_name       TEXT,
    approver_role   TEXT NOT NULL,  -- Partner|Manager
    approver_id     UUID,           -- specific user if targeted
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|escalated|expired
    title           TEXT NOT NULL,
    description     TEXT,
    context_data    JSONB NOT NULL DEFAULT '{}',
    due_at          TIMESTAMPTZ,
    escalation_at   TIMESTAMPTZ,
    escalated_to    TEXT,  -- role to escalate to after timeout
    responded_at    TIMESTAMPTZ,
    responder_id    UUID,
    response_notes  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_approvals_firm ON workflow_approvals(firm_id, status);
CREATE INDEX IF NOT EXISTS idx_wf_approvals_approver ON workflow_approvals(approver_id, status);
CREATE INDEX IF NOT EXISTS idx_wf_approvals_instance ON workflow_approvals(instance_id);

-- ── Workflow Schedules ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS workflow_schedules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL,
    template_id     UUID NOT NULL REFERENCES workflow_templates(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    cron_expression TEXT NOT NULL,  -- standard cron: "0 9 * * 1" = Mon 9am
    timezone        TEXT NOT NULL DEFAULT 'Asia/Kolkata',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    last_run_at     TIMESTAMPTZ,
    next_run_at     TIMESTAMPTZ,
    last_run_status TEXT,
    run_count       INTEGER NOT NULL DEFAULT 0,
    created_by      UUID,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_wf_schedules_firm ON workflow_schedules(firm_id, is_active);
CREATE INDEX IF NOT EXISTS idx_wf_schedules_next ON workflow_schedules(next_run_at) WHERE is_active = true;
