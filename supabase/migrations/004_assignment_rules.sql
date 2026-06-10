-- Phase 1.2: Assignment Rules Engine
-- Support role-based, team-based, and fallback assignment in recurring workflows
-- Idempotent migration — safe to run multiple times

-- Assignment rules: flexible assignment logic for recurring task configs
CREATE TABLE IF NOT EXISTS assignment_rules (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL,
  recurring_config_id UUID NOT NULL REFERENCES task_recurring_configs(id) ON DELETE CASCADE,
  rule_type TEXT NOT NULL CHECK (rule_type IN ('fixed_user', 'by_role', 'by_team', 'fallback')),
  target_value TEXT,  -- user_id for fixed_user, role for by_role, team_id for by_team, NULL for fallback
  priority INTEGER NOT NULL DEFAULT 0,  -- lower number = evaluated first
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assignment_rules_firm_id ON assignment_rules(firm_id);
CREATE INDEX IF NOT EXISTS idx_assignment_rules_recurring_config_id ON assignment_rules(recurring_config_id);
CREATE INDEX IF NOT EXISTS idx_assignment_rules_priority ON assignment_rules(recurring_config_id, priority) WHERE is_active = true;
