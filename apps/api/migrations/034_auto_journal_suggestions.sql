CREATE TABLE IF NOT EXISTS public.auto_journal_suggestions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  source_type TEXT NOT NULL CHECK (source_type IN ('salary', 'depreciation', 'loan_emi', 'fd_interest', 'gst_liability', 'tds_payable')),
  source_id TEXT, -- ID of the source record (employee_id, asset_id, etc.)
  period_month INTEGER NOT NULL,
  period_year INTEGER NOT NULL,
  description TEXT NOT NULL,
  lines JSONB NOT NULL, -- [{account_name, account_type, debit_paise, credit_paise}]
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'approved', 'dismissed')),
  journal_entry_id UUID REFERENCES public.journal_entries(id),
  created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.auto_journal_suggestions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_manage_suggestions" ON public.auto_journal_suggestions;
CREATE POLICY "firm_staff_manage_suggestions" ON public.auto_journal_suggestions
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.auto_journal_suggestions TO authenticated;
