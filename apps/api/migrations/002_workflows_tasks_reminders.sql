-- CAflow AI — Migration 002: Workflows, Tasks, Reminders
-- Operational backbone for CA practice management

-- ─── WORKFLOWS ─────────────────────────────────────────────────────────────
CREATE TABLE workflows (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    description TEXT,
    compliance_type TEXT CHECK (compliance_type IN (
        'GSTR1', 'GSTR3B', 'GSTR9', 'ITR', 'TDS24Q', 'TDS26Q',
        'ADVANCE_TAX', 'TCS_RETURN', 'GENERAL', 'OTHER'
    )),
    is_template BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- ─── WORKFLOW STEPS ────────────────────────────────────────────────────────
CREATE TABLE workflow_steps (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    workflow_id UUID NOT NULL REFERENCES workflows(id),
    step_name TEXT NOT NULL,
    step_description TEXT,
    step_order INTEGER NOT NULL,
    required BOOLEAN NOT NULL DEFAULT true,
    default_assignee_role TEXT CHECK (default_assignee_role IN ('owner', 'manager', 'staff', 'viewer')),
    estimated_hours NUMERIC(4,1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (workflow_id, step_order)
);

-- ─── TASKS ─────────────────────────────────────────────────────────────────
CREATE TABLE tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id),
    workflow_id UUID REFERENCES workflows(id),
    workflow_step_id UUID REFERENCES workflow_steps(id),
    title TEXT NOT NULL,
    description TEXT,
    status TEXT NOT NULL DEFAULT 'todo' CHECK (status IN (
        'todo', 'in_progress', 'waiting_client', 'review_required', 'completed'
    )),
    priority TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN (
        'low', 'medium', 'high', 'critical'
    )),
    assigned_to UUID REFERENCES team_members(id),
    due_date DATE,
    completed_at TIMESTAMPTZ,
    tags TEXT[],
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- ─── REMINDERS ─────────────────────────────────────────────────────────────
CREATE TABLE reminders (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id UUID REFERENCES tasks(id),
    client_id UUID REFERENCES clients(id),
    reminder_type TEXT NOT NULL CHECK (reminder_type IN ('email', 'whatsapp', 'system')),
    scheduled_for TIMESTAMPTZ NOT NULL,
    sent_at TIMESTAMPTZ,
    status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'sent', 'failed')),
    message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── INDEXES ───────────────────────────────────────────────────────────────
CREATE INDEX idx_tasks_client ON tasks(client_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_tasks_status ON tasks(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_tasks_due_date ON tasks(due_date) WHERE deleted_at IS NULL;
CREATE INDEX idx_tasks_assigned ON tasks(assigned_to) WHERE deleted_at IS NULL;
CREATE INDEX idx_tasks_workflow ON tasks(workflow_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_workflow_steps_workflow ON workflow_steps(workflow_id);
CREATE INDEX idx_reminders_scheduled ON reminders(scheduled_for) WHERE status = 'pending';
CREATE INDEX idx_reminders_task ON reminders(task_id);

CREATE TRIGGER trg_workflows_updated_at BEFORE UPDATE ON workflows FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_tasks_updated_at BEFORE UPDATE ON tasks FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_reminders_updated_at BEFORE UPDATE ON reminders FOR EACH ROW EXECUTE FUNCTION set_updated_at();
