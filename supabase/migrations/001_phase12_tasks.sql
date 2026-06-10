-- Phase 1.2: Task Management Enhancement
-- Idempotent migration — safe to run multiple times

-- Task templates: reusable blueprints for common CA work
CREATE TABLE IF NOT EXISTS task_templates (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID,  -- NULL = system-wide default template
  name TEXT NOT NULL,
  description TEXT,
  default_priority TEXT NOT NULL DEFAULT 'medium',
  estimated_hours INTEGER,
  tags TEXT[] DEFAULT '{}',
  default_assignee_role TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_task_templates_firm_id ON task_templates(firm_id);

-- Task tags: label tasks for filtering and organisation
CREATE TABLE IF NOT EXISTS task_tags (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL,
  task_id UUID NOT NULL,
  tag TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_task_tags_task_id ON task_tags(task_id);
CREATE INDEX IF NOT EXISTS idx_task_tags_firm_id ON task_tags(firm_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_task_tags_unique ON task_tags(task_id, tag);

-- Task dependencies: blocked-by relationships between tasks
CREATE TABLE IF NOT EXISTS task_dependencies (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL,
  depends_on_task_id UUID NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_task_deps_task_id ON task_dependencies(task_id);
CREATE INDEX IF NOT EXISTS idx_task_deps_depends_on ON task_dependencies(depends_on_task_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_task_deps_unique ON task_dependencies(task_id, depends_on_task_id);

-- Task timeline events: audit trail of changes to each task
CREATE TABLE IF NOT EXISTS task_timeline_events (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id UUID NOT NULL,
  firm_id UUID,
  event_type TEXT NOT NULL,
  actor_id TEXT,
  actor_name TEXT,
  old_value JSONB,
  new_value JSONB,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_task_timeline_task_id ON task_timeline_events(task_id);
CREATE INDEX IF NOT EXISTS idx_task_timeline_firm_id ON task_timeline_events(firm_id);
CREATE INDEX IF NOT EXISTS idx_task_timeline_created_at ON task_timeline_events(created_at DESC);

-- Recurring task configs: auto-generate tasks on a schedule
CREATE TABLE IF NOT EXISTS task_recurring_configs (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL,
  client_id UUID,
  template_id UUID REFERENCES task_templates(id) ON DELETE SET NULL,
  assignee_id UUID,
  title TEXT,  -- override template name if needed
  description TEXT,
  priority TEXT DEFAULT 'medium',
  frequency TEXT NOT NULL,  -- 'daily','weekly','monthly','quarterly','annual'
  next_due_date DATE NOT NULL,
  last_generated_at TIMESTAMPTZ,
  is_active BOOLEAN NOT NULL DEFAULT true,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_task_recurring_firm_id ON task_recurring_configs(firm_id);
CREATE INDEX IF NOT EXISTS idx_task_recurring_next_due ON task_recurring_configs(next_due_date) WHERE is_active = true;

-- Seed system-wide task templates for CA firms
INSERT INTO task_templates (id, firm_id, name, description, default_priority, estimated_hours, tags, default_assignee_role)
VALUES
  ('00000000-0000-0000-0000-000000000001', NULL, 'Monthly Bookkeeping', 'Monthly bookkeeping and bank reconciliation for client accounts', 'high', 8, ARRAY['bookkeeping','monthly'], 'staff'),
  ('00000000-0000-0000-0000-000000000002', NULL, 'GST Return (Monthly)', 'Monthly GSTR-1 and GSTR-3B filing workflow', 'critical', 4, ARRAY['gst','monthly'], 'staff'),
  ('00000000-0000-0000-0000-000000000003', NULL, 'TDS Return', 'Quarterly TDS return filing (Form 24Q/26Q)', 'high', 3, ARRAY['tds','quarterly'], 'staff'),
  ('00000000-0000-0000-0000-000000000004', NULL, 'Annual Accounts', 'Preparation and finalisation of annual financial statements', 'critical', 20, ARRAY['accounts','annual'], 'manager'),
  ('00000000-0000-0000-0000-000000000005', NULL, 'Payroll Processing', 'Monthly payroll computation and statutory compliance', 'high', 6, ARRAY['payroll','monthly'], 'staff')
ON CONFLICT (id) DO NOTHING;
