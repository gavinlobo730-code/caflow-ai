-- Migration 008: Fix Supabase linter warnings
-- Addresses: mutable search_path, anon execute on SECURITY DEFINER, RLS gaps, FK indexes

-- ─── FIX get_my_firm_id: search_path + revoke anon ───────────────────────────

CREATE OR REPLACE FUNCTION get_my_firm_id()
RETURNS UUID
LANGUAGE SQL
SECURITY DEFINER
STABLE
SET search_path = pg_catalog, public
AS $$
  SELECT firm_id FROM users WHERE auth_user_id = (SELECT auth.uid()) LIMIT 1;
$$;

REVOKE EXECUTE ON FUNCTION get_my_firm_id() FROM anon;
GRANT EXECUTE ON FUNCTION get_my_firm_id() TO authenticated;

-- ─── FIX users policy: use (select auth.uid()) to prevent per-row re-eval ────

DROP POLICY IF EXISTS "users_own_row" ON users;
CREATE POLICY "users_own_row" ON users
  FOR ALL USING (auth_user_id = (SELECT auth.uid()));

-- ─── ADD RLS POLICIES FOR TABLES WITH NO POLICIES ────────────────────────────

-- automation_executions
ALTER TABLE automation_executions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "automation_executions_own_firm" ON automation_executions;
CREATE POLICY "automation_executions_own_firm" ON automation_executions
  FOR ALL USING (firm_id = get_my_firm_id());

-- filings
ALTER TABLE filings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "filings_own_firm" ON filings;
CREATE POLICY "filings_own_firm" ON filings
  FOR ALL USING (firm_id = get_my_firm_id());

-- journal_lines (child of journal_entries — use parent firm_id)
ALTER TABLE journal_lines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "journal_lines_own_firm" ON journal_lines;
CREATE POLICY "journal_lines_own_firm" ON journal_lines
  FOR ALL USING (
    journal_entry_id IN (
      SELECT id FROM journal_entries WHERE firm_id = get_my_firm_id()
    )
  );

-- permission_grants
ALTER TABLE permission_grants ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "permission_grants_own_firm" ON permission_grants;
CREATE POLICY "permission_grants_own_firm" ON permission_grants
  FOR ALL USING (firm_id = get_my_firm_id());

-- reminders
ALTER TABLE reminders ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "reminders_own_firm" ON reminders;
CREATE POLICY "reminders_own_firm" ON reminders
  FOR ALL USING (firm_id = get_my_firm_id());

-- team_members
ALTER TABLE team_members ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "team_members_own_firm" ON team_members;
CREATE POLICY "team_members_own_firm" ON team_members
  FOR ALL USING (firm_id = get_my_firm_id());

-- workflow_steps (child of workflows)
ALTER TABLE workflow_steps ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "workflow_steps_own_firm" ON workflow_steps;
CREATE POLICY "workflow_steps_own_firm" ON workflow_steps
  FOR ALL USING (
    workflow_id IN (
      SELECT id FROM workflows WHERE firm_id = get_my_firm_id()
    )
  );

-- workflows
ALTER TABLE workflows ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "workflows_own_firm" ON workflows;
CREATE POLICY "workflows_own_firm" ON workflows
  FOR ALL USING (firm_id = get_my_firm_id());

-- ─── PERFORMANCE: INDEX UNINDEXED FOREIGN KEYS ───────────────────────────────

CREATE INDEX IF NOT EXISTS idx_tasks_client_id ON tasks(client_id);
CREATE INDEX IF NOT EXISTS idx_tasks_firm_id ON tasks(firm_id);
CREATE INDEX IF NOT EXISTS idx_tasks_assigned_to ON tasks(assigned_to);

CREATE INDEX IF NOT EXISTS idx_clients_firm_id ON clients(firm_id);

CREATE INDEX IF NOT EXISTS idx_documents_firm_id ON documents(firm_id);
CREATE INDEX IF NOT EXISTS idx_documents_client_id ON documents(client_id);

CREATE INDEX IF NOT EXISTS idx_journal_entries_firm_id ON journal_entries(firm_id);
CREATE INDEX IF NOT EXISTS idx_journal_entries_client_id ON journal_entries(client_id);

CREATE INDEX IF NOT EXISTS idx_compliance_calendar_firm_id ON compliance_calendar(firm_id);
CREATE INDEX IF NOT EXISTS idx_compliance_calendar_client_id ON compliance_calendar(client_id);

CREATE INDEX IF NOT EXISTS idx_transactions_firm_id ON transactions(firm_id);
CREATE INDEX IF NOT EXISTS idx_transactions_client_id ON transactions(client_id);

CREATE INDEX IF NOT EXISTS idx_transaction_lines_transaction_id ON transaction_lines(transaction_id);

CREATE INDEX IF NOT EXISTS idx_bank_statements_firm_id ON bank_statements(firm_id);
CREATE INDEX IF NOT EXISTS idx_bank_transactions_statement_id ON bank_transactions(statement_id);
CREATE INDEX IF NOT EXISTS idx_bank_transactions_firm_id ON bank_transactions(firm_id);

CREATE INDEX IF NOT EXISTS idx_filings_firm_id ON filings(firm_id) WHERE firm_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_filings_client_id ON filings(client_id) WHERE client_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_reminders_firm_id ON reminders(firm_id) WHERE firm_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_reminders_client_id ON reminders(client_id) WHERE client_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_team_members_firm_id ON team_members(firm_id) WHERE firm_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_team_members_user_id ON team_members(user_id) WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_workflows_firm_id ON workflows(firm_id) WHERE firm_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_workflow_steps_workflow_id ON workflow_steps(workflow_id) WHERE workflow_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_automation_executions_firm_id ON automation_executions(firm_id) WHERE firm_id IS NOT NULL;

-- ─── VERIFY ──────────────────────────────────────────────────────────────────
-- SELECT get_my_firm_id();   -- Should return your firm UUID (not NULL) from browser
-- SELECT proname, prosecdef, proacl FROM pg_proc WHERE proname = 'get_my_firm_id';
-- proacl should NOT contain 'anon=X'
