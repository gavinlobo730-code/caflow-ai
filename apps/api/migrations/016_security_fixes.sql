-- Migration 016: Security fixes from Supabase advisor
-- Fixes: SECURITY DEFINER views, anon role access, search_path injection

-- ─── 1. Fix SECURITY DEFINER views ──────────────────────────────────────────
-- These views bypass RLS — any authenticated user can read all firms' data.
-- Recreate them as SECURITY INVOKER (default) so RLS policies are enforced.

DROP VIEW IF EXISTS public.accounts CASCADE;
DROP VIEW IF EXISTS public.journal_entry_lines CASCADE;
DROP VIEW IF EXISTS public.compliance_entries CASCADE;

-- Recreate accounts view (security invoker = RLS enforced)
CREATE VIEW public.accounts
WITH (security_invoker = true)
AS
  SELECT * FROM public.chart_of_accounts;

-- Recreate journal_entry_lines view
CREATE VIEW public.journal_entry_lines
WITH (security_invoker = true)
AS
  SELECT
    jl.id,
    jl.journal_entry_id,
    jl.account_id,
    jl.debit_paise,
    jl.credit_paise,
    je.firm_id,
    je.entry_date,
    je.reference,
    coa.account_name,
    coa.account_code,
    coa.account_type
  FROM public.journal_lines jl
  JOIN public.journal_entries je ON je.id = jl.journal_entry_id
  JOIN public.chart_of_accounts coa ON coa.id = jl.account_id;

-- Recreate compliance_entries view
CREATE VIEW public.compliance_entries
WITH (security_invoker = true)
AS
  SELECT * FROM public.compliance_tasks;

-- Grant access to authenticated role
GRANT SELECT ON public.accounts TO authenticated;
GRANT SELECT ON public.journal_entry_lines TO authenticated;
GRANT SELECT ON public.compliance_entries TO authenticated;

-- ─── 2. Restrict get_my_firm_id() from anon role ─────────────────────────────
-- Currently callable without authentication — fix by revoking anon access.
REVOKE EXECUTE ON FUNCTION public.get_my_firm_id() FROM anon;
GRANT EXECUTE ON FUNCTION public.get_my_firm_id() TO authenticated;

-- ─── 3. Restrict rls_auto_enable() from anon role ────────────────────────────
REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon, public;
GRANT EXECUTE ON FUNCTION public.rls_auto_enable() TO authenticated;

-- ─── 4. Fix mutable search_path on functions ─────────────────────────────────
-- Prevents search_path injection attacks.

CREATE OR REPLACE FUNCTION public.get_my_firm_id()
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT firm_id FROM public.users WHERE id = auth.uid() LIMIT 1;
$$;

-- Re-grant after recreating
REVOKE EXECUTE ON FUNCTION public.get_my_firm_id() FROM anon;
GRANT EXECUTE ON FUNCTION public.get_my_firm_id() TO authenticated;

CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

-- ─── 5. RLS policies for tables with RLS enabled but no policies ─────────────
-- These tables block ALL queries without at least one policy.

-- automation_executions
CREATE POLICY "firm_isolation" ON public.automation_executions
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- filings
CREATE POLICY "firm_isolation" ON public.filings
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- journal_lines (accessed via journal_entries join)
CREATE POLICY "firm_isolation" ON public.journal_lines
  FOR ALL TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.journal_entries je
      WHERE je.id = journal_lines.journal_entry_id
        AND je.firm_id = public.get_my_firm_id()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.journal_entries je
      WHERE je.id = journal_lines.journal_entry_id
        AND je.firm_id = public.get_my_firm_id()
    )
  );

-- permission_grants
CREATE POLICY "firm_isolation" ON public.permission_grants
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- reminders
CREATE POLICY "firm_isolation" ON public.reminders
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- team_members
CREATE POLICY "firm_isolation" ON public.team_members
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- workflow_steps (via workflows join)
CREATE POLICY "firm_isolation" ON public.workflow_steps
  FOR ALL TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.workflows w
      WHERE w.id = workflow_steps.workflow_id
        AND w.firm_id = public.get_my_firm_id()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.workflows w
      WHERE w.id = workflow_steps.workflow_id
        AND w.firm_id = public.get_my_firm_id()
    )
  );

-- workflows
CREATE POLICY "firm_isolation" ON public.workflows
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- ─── 6. Performance: indexes for high-traffic foreign keys ───────────────────
-- Adding the most commonly queried FK columns (skipping ones already indexed).

CREATE INDEX IF NOT EXISTS idx_journal_lines_journal_entry_id ON public.journal_lines(journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_journal_lines_account_id ON public.journal_lines(account_id);
CREATE INDEX IF NOT EXISTS idx_journal_entries_firm_id ON public.journal_entries(firm_id);
CREATE INDEX IF NOT EXISTS idx_journal_entries_entry_date ON public.journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_clients_firm_id ON public.clients(firm_id);
CREATE INDEX IF NOT EXISTS idx_tasks_firm_id ON public.tasks(firm_id);
CREATE INDEX IF NOT EXISTS idx_tasks_client_id ON public.tasks(client_id);
CREATE INDEX IF NOT EXISTS idx_reminders_firm_id ON public.reminders(firm_id);
CREATE INDEX IF NOT EXISTS idx_filings_firm_id ON public.filings(firm_id);
CREATE INDEX IF NOT EXISTS idx_filings_client_id ON public.filings(client_id);
CREATE INDEX IF NOT EXISTS idx_compliance_tasks_firm_id ON public.compliance_tasks(firm_id);
CREATE INDEX IF NOT EXISTS idx_invoices_firm_id ON public.invoices(firm_id);
CREATE INDEX IF NOT EXISTS idx_invoices_client_id ON public.invoices(client_id);
