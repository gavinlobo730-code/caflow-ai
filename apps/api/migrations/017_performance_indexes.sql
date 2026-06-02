-- Migration 017: Performance indexes for high-traffic foreign keys
-- Run after all table migrations (014+) are applied.

CREATE INDEX IF NOT EXISTS idx_journal_lines_journal_entry_id ON public.journal_lines(journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_journal_lines_account_id ON public.journal_lines(account_id);
CREATE INDEX IF NOT EXISTS idx_journal_entries_firm_id ON public.journal_entries(firm_id);
CREATE INDEX IF NOT EXISTS idx_journal_entries_entry_date ON public.journal_entries(entry_date);
CREATE INDEX IF NOT EXISTS idx_clients_firm_id ON public.clients(firm_id);
CREATE INDEX IF NOT EXISTS idx_tasks_firm_id ON public.tasks(firm_id);
CREATE INDEX IF NOT EXISTS idx_tasks_client_id ON public.tasks(client_id);
CREATE INDEX IF NOT EXISTS idx_reminders_client_id ON public.reminders(client_id);
CREATE INDEX IF NOT EXISTS idx_filings_client_id ON public.filings(client_id);
CREATE INDEX IF NOT EXISTS idx_compliance_tasks_client_id ON public.compliance_tasks(client_id);
CREATE INDEX IF NOT EXISTS idx_fee_invoices_firm_id ON public.fee_invoices(firm_id);
CREATE INDEX IF NOT EXISTS idx_fee_invoices_client_id ON public.fee_invoices(client_id);
CREATE INDEX IF NOT EXISTS idx_sales_invoices_firm_id ON public.sales_invoices(firm_id);
CREATE INDEX IF NOT EXISTS idx_sales_invoices_client_id ON public.sales_invoices(client_id);
