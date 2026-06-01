-- Migration 010: Grant table permissions to authenticated role
-- ROOT CAUSE: Tables have RLS policies but no GRANT to authenticated role.
-- PostgreSQL denies access before even checking RLS if the role has no permission.
-- This is why "permission denied for table clients" appears — not an RLS issue.
--
-- Also creates an `accounts` view over `chart_of_accounts` so the frontend
-- can query .from("accounts") without renaming 9 files.

-- ─── CREATE accounts VIEW (frontend queries this, real table is chart_of_accounts)

CREATE OR REPLACE VIEW public.accounts AS
  SELECT * FROM public.chart_of_accounts;

-- Grant the view
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.accounts TO authenticated;

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
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chart_of_accounts   TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bank_statements     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bank_transactions   TO authenticated;

-- ─── GRANT SECONDARY TABLES ──────────────────────────────────────────────────

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.compliance_tasks    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.compliance_records  TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.reminders           TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.notifications       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.activity_logs       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.workflows           TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.automation_rules    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.automation_executions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ai_insights         TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.document_extractions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.document_risks      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.team_members        TO authenticated;

-- ─── GRANT SEQUENCE USAGE (needed for INSERT) ────────────────────────────────

GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO authenticated;
