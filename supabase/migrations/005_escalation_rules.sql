-- Phase 1.2: Escalation Rules Engine
-- Support configurable escalation for due-soon and overdue tasks
-- Idempotent migration — safe to run multiple times

-- Escalation rules: configurable rules for escalating tasks based on thresholds
CREATE TABLE IF NOT EXISTS escalation_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL,
  rule_type TEXT NOT NULL CHECK (rule_type IN ('due_soon', 'overdue', 'reassign_overdue', 'manager_notify')),
  days_threshold INTEGER NOT NULL,
  escalate_to_role TEXT,
  reassign_to_role TEXT,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_escalation_rules_firm_id ON escalation_rules(firm_id);
CREATE INDEX IF NOT EXISTS idx_escalation_rules_active ON escalation_rules(firm_id, rule_type) WHERE is_active = true;

-- Task escalations: audit trail of escalation events
CREATE TABLE IF NOT EXISTS task_escalations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL,
  escalation_rule_id UUID NOT NULL REFERENCES escalation_rules(id) ON DELETE CASCADE,
  escalated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  escalation_type TEXT NOT NULL CHECK (escalation_type IN ('due_soon', 'overdue', 'reassigned'))
);

CREATE INDEX IF NOT EXISTS idx_task_escalations_task_id ON task_escalations(task_id);
CREATE INDEX IF NOT EXISTS idx_task_escalations_rule_id ON task_escalations(escalation_rule_id);
CREATE INDEX IF NOT EXISTS idx_task_escalations_escalated_at ON task_escalations(escalated_at DESC);
