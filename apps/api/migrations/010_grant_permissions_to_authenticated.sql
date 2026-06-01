-- Migration 010: Grant table permissions to authenticated role
-- ROOT CAUSE: Tables have RLS policies but no GRANT to authenticated role.
-- PostgreSQL denies access before even checking RLS if the role has no permission.
-- This is why "permission denied for table clients" appears — not an RLS issue.

-- ─── GRANT ALL CORE TABLES TO authenticated ──────────────────────────────────

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.users               TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.firms               TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.clients             TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tasks               TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.documents           TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.compliance_calendar TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.transactions        TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.transaction_lines   TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.journal_entries     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.journal_lines       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.accounts            TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bank_statements     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bank_transactions   TO authenticated;

-- ─── GRANT SECONDARY TABLES ──────────────────────────────────────────────────

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.compliance_tasks    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.compliance_records  TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.reminders           TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.notifications       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.activity_logs       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.workflows           TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.workflow_steps      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.automation_rules    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.automation_executions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ai_insights         TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.document_extractions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.document_risks      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.filings             TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.team_members        TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.permission_grants   TO authenticated;

-- ─── GRANT SEQUENCE USAGE (needed for INSERT with serial/uuid columns) ────────

GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO authenticated;

-- ─── VERIFY ──────────────────────────────────────────────────────────────────
-- After running, test from the browser — clients/tasks/dashboard should all load.
-- The RLS policies (firm_id = get_my_firm_id()) will still enforce data isolation.
-- GRANT just allows the role to attempt the query; RLS controls what rows are returned.
