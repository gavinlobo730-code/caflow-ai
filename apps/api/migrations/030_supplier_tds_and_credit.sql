-- Supplier master with TDS section mapping
CREATE TABLE IF NOT EXISTS public.suppliers (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  supplier_name TEXT NOT NULL,
  gstin TEXT,
  pan TEXT,
  tds_section TEXT, -- e.g. '194C', '194I', '194J', '194L', NULL means no TDS
  tds_rate_percent NUMERIC(5,2),
  credit_limit_paise BIGINT DEFAULT 0,
  payment_terms_days INTEGER DEFAULT 30,
  is_active BOOLEAN DEFAULT true,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.suppliers ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_manage_suppliers" ON public.suppliers
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- Customer credit limits and aging
ALTER TABLE public.clients
  ADD COLUMN IF NOT EXISTS credit_limit_paise BIGINT DEFAULT 0,
  ADD COLUMN IF NOT EXISTS payment_terms_days INTEGER DEFAULT 30;

-- Capital gains register
CREATE TABLE IF NOT EXISTS public.capital_gains (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  asset_description TEXT NOT NULL,
  asset_type TEXT NOT NULL CHECK (asset_type IN ('equity_shares', 'mutual_funds', 'property', 'bonds', 'other')),
  purchase_date DATE NOT NULL,
  sale_date DATE NOT NULL,
  purchase_cost_paise BIGINT NOT NULL,
  improvement_cost_paise BIGINT NOT NULL DEFAULT 0,
  sale_value_paise BIGINT NOT NULL,
  indexed_cost_paise BIGINT, -- computed using Cost Inflation Index
  gain_type TEXT, -- 'STCG' or 'LTCG' (computed)
  tax_rate_percent NUMERIC(5,2), -- STCG: 15/20%, LTCG: 10/20%
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.capital_gains ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_manage_capital_gains" ON public.capital_gains
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.suppliers TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.capital_gains TO authenticated;
