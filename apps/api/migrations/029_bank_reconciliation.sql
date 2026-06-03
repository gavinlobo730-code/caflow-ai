ALTER TABLE public.bank_transactions
  ADD COLUMN IF NOT EXISTS reconciled BOOLEAN DEFAULT false,
  ADD COLUMN IF NOT EXISTS reconciled_journal_id UUID REFERENCES public.journal_entries(id),
  ADD COLUMN IF NOT EXISTS reconciled_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS public.bank_reconciliations (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  account_no TEXT,
  period_start DATE NOT NULL,
  period_end DATE NOT NULL,
  opening_balance_paise BIGINT NOT NULL DEFAULT 0,
  closing_balance_paise BIGINT NOT NULL DEFAULT 0,
  status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closed')),
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.bank_reconciliations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_manage_reconciliations" ON public.bank_reconciliations
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
