CREATE TABLE IF NOT EXISTS public.loans (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  loan_type TEXT NOT NULL CHECK (loan_type IN ('term_loan', 'overdraft', 'cc', 'home_loan', 'vehicle_loan', 'personal_loan', 'other')),
  lender_name TEXT NOT NULL,
  account_number TEXT,
  principal_paise BIGINT NOT NULL,
  outstanding_paise BIGINT NOT NULL,
  interest_rate_percent NUMERIC(5,2) NOT NULL,
  emi_paise BIGINT,
  disbursement_date DATE NOT NULL,
  maturity_date DATE,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'closed', 'overdue')),
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS public.fixed_deposits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  bank_name TEXT NOT NULL,
  fd_number TEXT,
  principal_paise BIGINT NOT NULL,
  interest_rate_percent NUMERIC(5,2) NOT NULL,
  start_date DATE NOT NULL,
  maturity_date DATE NOT NULL,
  maturity_amount_paise BIGINT NOT NULL,
  is_auto_renewed BOOLEAN DEFAULT false,
  tds_applicable BOOLEAN DEFAULT true,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'matured', 'broken')),
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.loans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fixed_deposits ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_staff_manage_loans" ON public.loans
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

CREATE POLICY "firm_staff_manage_fds" ON public.fixed_deposits
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
