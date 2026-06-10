-- Migration 046: Escalation Rules for Task Management
-- Stores configurable escalation rules and audit trail of escalation events

CREATE TABLE IF NOT EXISTS public.escalation_rules (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  rule_type TEXT NOT NULL CHECK (rule_type IN ('due_soon', 'overdue', 'reassign_overdue', 'manager_notify')),
  days_threshold INTEGER NOT NULL,
  escalate_to_role TEXT,
  reassign_to_role TEXT,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.task_escalations (
  id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
  task_id UUID NOT NULL REFERENCES public.tasks(id) ON DELETE CASCADE,
  escalation_rule_id UUID NOT NULL REFERENCES public.escalation_rules(id) ON DELETE CASCADE,
  escalated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  escalation_type TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_escalation_rules_firm_id ON public.escalation_rules(firm_id);
CREATE INDEX IF NOT EXISTS idx_escalation_rules_active ON public.escalation_rules(firm_id, rule_type) WHERE is_active = true;
CREATE INDEX IF NOT EXISTS idx_task_escalations_task_id ON public.task_escalations(task_id);
CREATE INDEX IF NOT EXISTS idx_task_escalations_escalated_at ON public.task_escalations(escalated_at DESC);

ALTER TABLE public.escalation_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.task_escalations ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "escalation_rules_own_firm" ON public.escalation_rules;
CREATE POLICY "escalation_rules_own_firm" ON public.escalation_rules
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "task_escalations_own_firm" ON public.task_escalations;
CREATE POLICY "task_escalations_own_firm" ON public.task_escalations
  FOR ALL USING (
    task_id IN (SELECT id FROM public.tasks WHERE firm_id = get_my_firm_id())
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.escalation_rules TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.escalation_rules TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.task_escalations TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.task_escalations TO service_role;
