-- Migration 041: Grant authenticated role access to ALL tables
-- Run in Supabase SQL Editor to fix "permission denied" and RLS errors
-- across the entire application.

GRANT USAGE ON SCHEMA public TO authenticated, service_role;

-- Core tables
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.users TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.firms TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.clients TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tasks TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.documents TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.compliance_calendar TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.compliance_tasks TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.compliance_records TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.transactions TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.transaction_lines TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.journal_entries TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.journal_lines TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.chart_of_accounts TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bank_statements TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bank_transactions TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.reminders TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.notifications TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.activity_logs TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.workflows TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.workflow_steps TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.automation_rules TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.automation_executions TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ai_insights TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.document_extractions TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.document_risks TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.team_members TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.ledger_balances TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.filings TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.permission_grants TO authenticated, service_role;

-- Extended tables
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.fixed_assets TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.fixed_deposits TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.loans TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.gst_challans TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.gstr1_returns TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.gstr2a_records TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.gstr3b_returns TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.hsn_master TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tds_deductions TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tds_challans TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tds_returns TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tds_certificates TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tds_section_limits TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.advance_tax_payments TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.capital_gains TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.it_deductions TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.it_notices TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tax_notices TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tax_audit_checklists TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tax_audits TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.tax_planning_records TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.mca_companies TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.mca_directors TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.mca_filings TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.payroll_employees TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.payroll_runs TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.payroll_slips TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.attendance TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.leave_balances TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.fee_engagements TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.fee_invoices TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.fee_receipts TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.retainer_clients TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.retainer_logs TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.sales_invoices TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.invoice_lines TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.suppliers TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.msme_vendors TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.msme_payments TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bank_reconciliations TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.bank_reconciliation_matches TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.auto_journal_suggestions TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.client_documents TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.document_requests TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.dsc_records TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.shared_reports TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.scheduled_reports TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.user_client_assignments TO authenticated, service_role;

-- All sequences (needed for INSERT)
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO authenticated, service_role;

-- RLS: ensure clients policy allows insert with firm_id
DROP POLICY IF EXISTS "clients_own_firm" ON public.clients;
CREATE POLICY "clients_own_firm" ON public.clients
  FOR ALL USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- RLS: fixed_assets policy
ALTER TABLE IF EXISTS public.fixed_assets ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "fixed_assets_own_firm" ON public.fixed_assets;
CREATE POLICY "fixed_assets_own_firm" ON public.fixed_assets
  FOR ALL USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
