CREATE TABLE IF NOT EXISTS public.fixed_assets (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  asset_name TEXT NOT NULL,
  asset_category TEXT NOT NULL, -- Building, Plant & Machinery, Furniture, Vehicle, Computer, Intangible, Other
  purchase_date DATE NOT NULL,
  purchase_cost_paise BIGINT NOT NULL, -- integer paise, never float
  salvage_value_paise BIGINT NOT NULL DEFAULT 0,
  useful_life_years INTEGER, -- for SL method
  depreciation_method TEXT NOT NULL DEFAULT 'WDV' CHECK (depreciation_method IN ('SL', 'WDV')),
  wdv_rate_percent NUMERIC(5,2), -- e.g. 15.00 for 15%
  accumulated_depreciation_paise BIGINT NOT NULL DEFAULT 0,
  is_disposed BOOLEAN DEFAULT false,
  disposal_date DATE,
  disposal_value_paise BIGINT,
  notes TEXT,
  created_at TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.fixed_assets ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_staff_manage_assets" ON public.fixed_assets
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
