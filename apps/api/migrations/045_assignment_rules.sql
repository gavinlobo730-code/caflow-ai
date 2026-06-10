-- Migration 045: Assignment Rules for Recurring Workflows
-- Stores configurable assignment rules for recurring task auto-generation

CREATE TABLE IF NOT EXISTS public.assignment_rules (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  recurring_config_id UUID NOT NULL REFERENCES public.task_recurring_configs(id) ON DELETE CASCADE,
  rule_type TEXT NOT NULL CHECK (rule_type IN ('fixed_user', 'by_role', 'by_team', 'fallback')),
  target_value TEXT,
  priority INTEGER NOT NULL DEFAULT 100,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_assignment_rules_firm_id ON public.assignment_rules(firm_id);
CREATE INDEX IF NOT EXISTS idx_assignment_rules_recurring_config ON public.assignment_rules(recurring_config_id);
CREATE INDEX IF NOT EXISTS idx_assignment_rules_priority ON public.assignment_rules(recurring_config_id, priority) WHERE is_active = true;

ALTER TABLE public.assignment_rules ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "assignment_rules_own_firm" ON public.assignment_rules;
CREATE POLICY "assignment_rules_own_firm" ON public.assignment_rules
  FOR ALL USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.assignment_rules TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.assignment_rules TO service_role;
