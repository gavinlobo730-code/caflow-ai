-- ============================================================================
-- 157: Workflow engine schema repair (audit F11/F12; roadmap R2.7).
--
-- Migration 068 (Phase-10 workflow engine) never fully applies on a fresh
-- database: its CREATE TABLE IF NOT EXISTS workflow_steps silently no-ops
-- against 002's legacy same-named table, then its index on the (never added)
-- template_id column errors and aborts the file — so workflow_instances,
-- workflow_action_logs, workflow_executions, workflow_failures,
-- workflow_approvals and workflow_schedules NEVER EXIST, and 071's RLS pass
-- fails in cascade. Only workflow_templates (created before the abort)
-- survives, with no RLS/grants (154's guards skipped the missing tables).
--
-- Same repair pattern as 155 (year-end): a NEW migration that additively
-- reconciles the legacy table to the shape the code needs and creates the
-- missing tables — never editing old migration files. 068/071 stay in the
-- documented EXPECTED_MIGRATION_FAILURES baseline (they still fail on their
-- own); this file supersedes them.
--
-- workflow_triggers / workflow_conditions (068's other two tables) are NOT
-- created: the engine reads trigger_type/trigger_config/conditions straight
-- off workflow_templates (JSONB) — those tables were dead by design (zero
-- code references, confirmed R2.2 dead-table sweep).
-- ============================================================================

-- ─── workflow_steps: reconcile 002's legacy shape to 068's engine shape ─────
-- 002 created (workflow_id NOT NULL, step_name NOT NULL, step_order, …);
-- the v2 engine needs 068's columns. Additive + constraint relaxation so
-- BOTH shapes coexist: legacy rows keep their columns, engine rows use the
-- new ones.

ALTER TABLE public.workflow_steps
  ADD COLUMN IF NOT EXISTS template_id UUID REFERENCES public.workflow_templates(id) ON DELETE CASCADE,
  ADD COLUMN IF NOT EXISTS step_type TEXT,
  ADD COLUMN IF NOT EXISTS name TEXT,
  ADD COLUMN IF NOT EXISTS description TEXT,
  ADD COLUMN IF NOT EXISTS config JSONB NOT NULL DEFAULT '{}',
  ADD COLUMN IF NOT EXISTS next_step_id UUID,
  ADD COLUMN IF NOT EXISTS true_branch_step_id UUID,
  ADD COLUMN IF NOT EXISTS false_branch_step_id UUID;

-- 002's NOT NULLs would reject engine-shaped rows (which have no legacy
-- workflow_id/step_name). Relax them; legacy writers (none exist — the
-- legacy tables are dead code) are unaffected. Existence-guarded (065
-- pattern): on a hand-bootstrapped database where 068's CREATE TABLE won
-- instead of 002's (so these columns never existed at all), a bare ALTER
-- COLUMN would error and — since the runner applies statement-by-statement,
-- not in one transaction — abort before the six tables below ever get
-- created (R2.7 adversarial-review finding).
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'workflow_steps' AND column_name = 'workflow_id'
  ) THEN
    ALTER TABLE public.workflow_steps ALTER COLUMN workflow_id DROP NOT NULL;
  END IF;
  IF EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name = 'workflow_steps' AND column_name = 'step_name'
  ) THEN
    ALTER TABLE public.workflow_steps ALTER COLUMN step_name DROP NOT NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_wf_steps_template ON public.workflow_steps(template_id);

-- ─── Missing engine tables (068's DDL, plus idempotency_key which the
--     repository requires but 068 never had) ────────────────────────────────

CREATE TABLE IF NOT EXISTS public.workflow_instances (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL,
    template_id     UUID NOT NULL REFERENCES public.workflow_templates(id),
    client_id       UUID,
    trigger_event   TEXT NOT NULL,
    trigger_data    JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|running|completed|failed|cancelled|waiting_approval
    current_step_id UUID,
    context_data    JSONB NOT NULL DEFAULT '{}',
    idempotency_key TEXT,                             -- repo dedupes re-fired triggers on this
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    failed_at       TIMESTAMPTZ,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
-- Self-heal for databases that got 068's instances table some other way.
ALTER TABLE public.workflow_instances ADD COLUMN IF NOT EXISTS idempotency_key TEXT;

CREATE INDEX IF NOT EXISTS idx_wf_instances_firm ON public.workflow_instances(firm_id);
CREATE INDEX IF NOT EXISTS idx_wf_instances_template ON public.workflow_instances(template_id);
CREATE INDEX IF NOT EXISTS idx_wf_instances_client ON public.workflow_instances(client_id);
CREATE INDEX IF NOT EXISTS idx_wf_instances_status ON public.workflow_instances(firm_id, status);
CREATE INDEX IF NOT EXISTS idx_wf_instances_idem ON public.workflow_instances(firm_id, idempotency_key);

CREATE TABLE IF NOT EXISTS public.workflow_action_logs (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id UUID NOT NULL REFERENCES public.workflow_instances(id) ON DELETE CASCADE,
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
CREATE INDEX IF NOT EXISTS idx_wf_action_logs_instance ON public.workflow_action_logs(instance_id);
CREATE INDEX IF NOT EXISTS idx_wf_action_logs_status ON public.workflow_action_logs(status);

CREATE TABLE IF NOT EXISTS public.workflow_executions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id UUID NOT NULL REFERENCES public.workflow_instances(id) ON DELETE CASCADE,
    firm_id     UUID NOT NULL,
    event_type  TEXT NOT NULL,
    event_data  JSONB NOT NULL DEFAULT '{}',
    actor_id    UUID,
    actor_type  TEXT DEFAULT 'system',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wf_executions_instance ON public.workflow_executions(instance_id);
CREATE INDEX IF NOT EXISTS idx_wf_executions_firm ON public.workflow_executions(firm_id);

CREATE TABLE IF NOT EXISTS public.workflow_failures (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id UUID NOT NULL REFERENCES public.workflow_instances(id) ON DELETE CASCADE,
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
CREATE INDEX IF NOT EXISTS idx_wf_failures_firm ON public.workflow_failures(firm_id, resolved);
CREATE INDEX IF NOT EXISTS idx_wf_failures_instance ON public.workflow_failures(instance_id);

CREATE TABLE IF NOT EXISTS public.workflow_approvals (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    instance_id     UUID NOT NULL REFERENCES public.workflow_instances(id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL,
    step_id         UUID,
    step_name       TEXT,
    approver_role   TEXT NOT NULL,
    approver_id     UUID,
    status          TEXT NOT NULL DEFAULT 'pending',  -- pending|approved|rejected|escalated|expired
    title           TEXT NOT NULL,
    description     TEXT,
    context_data    JSONB NOT NULL DEFAULT '{}',
    due_at          TIMESTAMPTZ,
    escalation_at   TIMESTAMPTZ,
    escalated_to    TEXT,
    responded_at    TIMESTAMPTZ,
    responder_id    UUID,
    response_notes  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_wf_approvals_firm ON public.workflow_approvals(firm_id, status);
CREATE INDEX IF NOT EXISTS idx_wf_approvals_approver ON public.workflow_approvals(approver_id, status);
CREATE INDEX IF NOT EXISTS idx_wf_approvals_instance ON public.workflow_approvals(instance_id);

CREATE TABLE IF NOT EXISTS public.workflow_schedules (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    firm_id         UUID NOT NULL,
    template_id     UUID NOT NULL REFERENCES public.workflow_templates(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    cron_expression TEXT NOT NULL,
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
CREATE INDEX IF NOT EXISTS idx_wf_schedules_firm ON public.workflow_schedules(firm_id, is_active);
CREATE INDEX IF NOT EXISTS idx_wf_schedules_next ON public.workflow_schedules(next_run_at) WHERE is_active = true;

-- ─── RLS + grants (154/156 pattern) — including workflow_templates, which
--     068 created but nothing ever secured, and the legacy 002 tables the
--     engine now shares a table with ─────────────────────────────────────────

-- Firm-owned OR system (built-in) templates — matches the repository's own
-- read predicate (workflow_repository.py: `.or_("firm_id.eq.{firm_id},
-- is_system.eq.true")`). Today the backend reads via the service-role client
-- (RLS bypassed), so this only matters once the staged per-user-JWT cutover
-- (USE_USER_JWT) is enabled — get it right now, not as a surprise then.
ALTER TABLE public.workflow_templates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.workflow_templates;
CREATE POLICY "firm_isolation" ON public.workflow_templates
    USING (firm_id = get_my_firm_id() OR is_system = true);
GRANT SELECT, INSERT, UPDATE, DELETE ON public.workflow_templates TO authenticated, service_role;

-- workflow_steps has no firm_id (both shapes key off their parent). Scope
-- rows through the owning template; legacy workflow_id rows (dead code,
-- no readers) are firm-invisible, which is strictly safer than before
-- (002 shipped the table with RLS never enabled).
ALTER TABLE public.workflow_steps ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation_via_template" ON public.workflow_steps;
CREATE POLICY "firm_isolation_via_template" ON public.workflow_steps
    USING (EXISTS (
        SELECT 1 FROM public.workflow_templates t
        WHERE t.id = workflow_steps.template_id
          AND (t.firm_id = get_my_firm_id() OR t.is_system = true)
    ));
GRANT SELECT, INSERT, UPDATE, DELETE ON public.workflow_steps TO authenticated, service_role;

ALTER TABLE public.workflow_instances ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.workflow_instances;
CREATE POLICY "firm_isolation" ON public.workflow_instances
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.workflow_instances TO authenticated, service_role;

ALTER TABLE public.workflow_action_logs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation_via_instance" ON public.workflow_action_logs;
CREATE POLICY "firm_isolation_via_instance" ON public.workflow_action_logs
    USING (EXISTS (
        SELECT 1 FROM public.workflow_instances i
        WHERE i.id = workflow_action_logs.instance_id
          AND i.firm_id = get_my_firm_id()
    ));
GRANT SELECT, INSERT, UPDATE, DELETE ON public.workflow_action_logs TO authenticated, service_role;

ALTER TABLE public.workflow_executions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.workflow_executions;
CREATE POLICY "firm_isolation" ON public.workflow_executions
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.workflow_executions TO authenticated, service_role;

ALTER TABLE public.workflow_failures ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.workflow_failures;
CREATE POLICY "firm_isolation" ON public.workflow_failures
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.workflow_failures TO authenticated, service_role;

ALTER TABLE public.workflow_approvals ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.workflow_approvals;
CREATE POLICY "firm_isolation" ON public.workflow_approvals
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.workflow_approvals TO authenticated, service_role;

ALTER TABLE public.workflow_schedules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.workflow_schedules;
CREATE POLICY "firm_isolation" ON public.workflow_schedules
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.workflow_schedules TO authenticated, service_role;

-- ─── notifications.type: admit workflow-generated notifications ──────────────
-- The engine's send_notification action (F12 fix) writes real rows through
-- notifications_repository; the CHECK didn't anticipate a 'workflow' source.
--
-- CAUGHT BY ADVERSARIAL REVIEW: an earlier draft of this ALTER rebuilt the
-- CHECK from migration 004's original 6-type list + 'workflow' — silently
-- REVERTING migration 122's later widen (which added task_reassigned/
-- due_soon/overdue/task_overdue/recurring_generated after those types were
-- found to cause silent notification-write failures in production). This
-- version is a superset of 122's list, never a replacement of it — the next
-- widen must always extend the CURRENT constraint, not re-derive it from an
-- older migration.
ALTER TABLE public.notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE public.notifications ADD CONSTRAINT notifications_type_check CHECK (type IN (
    'task_assigned', 'risk_detected', 'document_processed',
    'compliance_due', 'ai_recommendation', 'status_changed',
    'task_reassigned', 'due_soon', 'overdue', 'task_overdue',
    'recurring_generated',
    'workflow'
));
