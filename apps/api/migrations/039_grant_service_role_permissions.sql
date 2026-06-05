-- Migration 039: Grant service_role full access to all tables
-- REQUIRED: The FastAPI backend uses SUPABASE_SERVICE_ROLE_KEY which runs as
-- the service_role Postgres role. Without explicit grants, service_role gets
-- "permission denied for table X" even though it bypasses RLS.
-- Run this in Supabase Dashboard → SQL Editor.

GRANT USAGE ON SCHEMA public TO service_role;

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.users               TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.firms               TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.clients             TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tasks               TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.documents           TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.compliance_calendar TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.compliance_tasks    TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.compliance_records  TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.transactions        TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.transaction_lines   TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.journal_entries     TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.journal_lines       TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chart_of_accounts   TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bank_statements     TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bank_transactions   TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.reminders           TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.notifications       TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.activity_logs       TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.workflows           TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.automation_rules    TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.automation_executions TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ai_insights         TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.document_extractions TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.document_risks      TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.team_members        TO service_role;

GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO service_role;

-- Allow service_role to query the accounts view
GRANT SELECT ON TABLE public.accounts TO service_role;
