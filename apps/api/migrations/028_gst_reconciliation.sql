-- GSTR-2A records (auto-populated ITC from supplier filings)
CREATE TABLE IF NOT EXISTS public.gstr2a_records (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  return_period TEXT NOT NULL, -- e.g. "042025" (MMYYYY)
  supplier_gstin TEXT NOT NULL,
  supplier_name TEXT,
  invoice_number TEXT NOT NULL,
  invoice_date DATE,
  taxable_value_paise BIGINT NOT NULL DEFAULT 0,
  igst_paise BIGINT NOT NULL DEFAULT 0,
  cgst_paise BIGINT NOT NULL DEFAULT 0,
  sgst_paise BIGINT NOT NULL DEFAULT 0,
  source TEXT DEFAULT 'manual', -- 'manual' or 'upload'
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.gstr2a_records ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_manage_gstr2a" ON public.gstr2a_records
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
