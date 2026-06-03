-- Migration 035: Complete missing pages — MSME payments, advance tax, IT notices, tax audits, IT deductions
-- All tables use integer paise arithmetic — no floating point

-- ─── MSME Payments (IT Act Section 43B(h)) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.msme_payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  supplier_name TEXT NOT NULL,
  invoice_number TEXT,
  invoice_date DATE NOT NULL,
  amount_paise BIGINT NOT NULL,
  agreement_type TEXT NOT NULL DEFAULT 'oral' CHECK (agreement_type IN ('written', 'oral')),
  payment_date DATE,
  created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.msme_payments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_manage_msme" ON public.msme_payments;
CREATE POLICY "firm_staff_manage_msme" ON public.msme_payments
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.msme_payments TO authenticated;

-- ─── Advance Tax Payments (IT Act Section 207/208/234B/234C) ─────────────────
CREATE TABLE IF NOT EXISTS public.advance_tax_payments (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year TEXT NOT NULL,
  installment_number INTEGER NOT NULL CHECK (installment_number BETWEEN 1 AND 4),
  due_date DATE NOT NULL,
  required_percent INTEGER NOT NULL,
  estimated_tax_paise BIGINT NOT NULL DEFAULT 0,
  paid_amount_paise BIGINT NOT NULL DEFAULT 0,
  paid_date DATE,
  challan_number TEXT,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(client_id, financial_year, installment_number)
);
ALTER TABLE public.advance_tax_payments ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_manage_advance_tax" ON public.advance_tax_payments;
CREATE POLICY "firm_staff_manage_advance_tax" ON public.advance_tax_payments
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.advance_tax_payments TO authenticated;

-- ─── IT Notices (IT Act Sections 143(1), 148, 271, etc.) ─────────────────────
CREATE TABLE IF NOT EXISTS public.it_notices (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  notice_type TEXT NOT NULL,
  assessment_year TEXT NOT NULL,
  date_received DATE NOT NULL,
  amount_demanded_paise BIGINT DEFAULT 0,
  response_due_date DATE,
  status TEXT NOT NULL DEFAULT 'pending' CHECK (status IN ('pending', 'responded', 'closed', 'appeal')),
  notice_storage_path TEXT,
  response_storage_path TEXT,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.it_notices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_manage_it_notices" ON public.it_notices;
CREATE POLICY "firm_staff_manage_it_notices" ON public.it_notices
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.it_notices TO authenticated;

-- ─── Tax Audits (IT Act Section 44AB) ────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.tax_audits (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year TEXT NOT NULL,
  form_type TEXT NOT NULL DEFAULT '3CB-3CD' CHECK (form_type IN ('3CA-3CD', '3CB-3CD')),
  status TEXT NOT NULL DEFAULT 'not_started' CHECK (status IN ('not_started', 'in_progress', 'completed', 'filed')),
  auditor_name TEXT,
  audit_date DATE,
  filing_date DATE,
  udin TEXT,
  ack_number TEXT,
  turnover_paise BIGINT DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now(),
  UNIQUE(client_id, financial_year)
);
ALTER TABLE public.tax_audits ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_manage_tax_audits" ON public.tax_audits;
CREATE POLICY "firm_staff_manage_tax_audits" ON public.tax_audits
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.tax_audits TO authenticated;

-- ─── IT Deductions (IT Act Section 80C, 80D, 80G, etc.) ──────────────────────
CREATE TABLE IF NOT EXISTS public.it_deductions (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year TEXT NOT NULL,
  deduction_type TEXT NOT NULL CHECK (deduction_type IN ('80C','80D','80G','80TTA','80U','HRA','LTA','Other')),
  description TEXT,
  amount_paid_paise BIGINT NOT NULL DEFAULT 0,
  eligible_amount_paise BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.it_deductions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_manage_it_deductions" ON public.it_deductions;
CREATE POLICY "firm_staff_manage_it_deductions" ON public.it_deductions
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.it_deductions TO authenticated;
