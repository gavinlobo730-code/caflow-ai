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
    je.reference_no,
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
DO $$ BEGIN
  REVOKE EXECUTE ON FUNCTION public.rls_auto_enable() FROM anon;
EXCEPTION WHEN undefined_function THEN NULL; END $$;

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
-- DROP first to make this idempotent (safe to re-run).

DROP POLICY IF EXISTS "firm_isolation" ON public.automation_executions;
DROP POLICY IF EXISTS "firm_isolation" ON public.filings;
DROP POLICY IF EXISTS "firm_isolation" ON public.journal_lines;
DROP POLICY IF EXISTS "user_isolation" ON public.permission_grants;
DROP POLICY IF EXISTS "firm_isolation" ON public.permission_grants;
DROP POLICY IF EXISTS "firm_isolation" ON public.reminders;
DROP POLICY IF EXISTS "firm_isolation" ON public.team_members;
DROP POLICY IF EXISTS "firm_isolation" ON public.workflow_steps;
DROP POLICY IF EXISTS "firm_isolation" ON public.workflows;

-- automation_executions (no firm_id — isolated via rule_id → automation_rules.firm_id)
CREATE POLICY "firm_isolation" ON public.automation_executions
  FOR ALL TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.automation_rules ar
      WHERE ar.id = automation_executions.rule_id
        AND ar.firm_id = public.get_my_firm_id()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.automation_rules ar
      WHERE ar.id = automation_executions.rule_id
        AND ar.firm_id = public.get_my_firm_id()
    )
  );

-- filings (no firm_id — isolated via client_id → clients.firm_id)
CREATE POLICY "firm_isolation" ON public.filings
  FOR ALL TO authenticated
  USING (
    EXISTS (
      SELECT 1 FROM public.clients c
      WHERE c.id = filings.client_id
        AND c.firm_id = public.get_my_firm_id()
    )
  )
  WITH CHECK (
    EXISTS (
      SELECT 1 FROM public.clients c
      WHERE c.id = filings.client_id
        AND c.firm_id = public.get_my_firm_id()
    )
  );

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

-- permission_grants (no firm_id — user-scoped, restrict to own records)
CREATE POLICY "user_isolation" ON public.permission_grants
  FOR ALL TO authenticated
  USING (user_id = auth.uid() OR granted_by = auth.uid())
  WITH CHECK (granted_by = auth.uid());

-- reminders (no firm_id — isolated via client_id → clients.firm_id)
CREATE POLICY "firm_isolation" ON public.reminders
  FOR ALL TO authenticated
  USING (
    client_id IS NULL OR EXISTS (
      SELECT 1 FROM public.clients c
      WHERE c.id = reminders.client_id
        AND c.firm_id = public.get_my_firm_id()
    )
  )
  WITH CHECK (
    client_id IS NULL OR EXISTS (
      SELECT 1 FROM public.clients c
      WHERE c.id = reminders.client_id
        AND c.firm_id = public.get_my_firm_id()
    )
  );

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
