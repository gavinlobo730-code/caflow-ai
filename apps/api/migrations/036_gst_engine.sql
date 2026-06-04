-- Migration 036: GST Engine — filing-ready schema additions
-- Adds invoice classification, GSTR-1/3B return tables, HSN master, challan tracking
-- All monetary values in integer paise — CGST Act Section 145A
-- Backward compatible: all new columns have DEFAULT values

-- ─── 1. Extend transactions table ────────────────────────────────────────────

ALTER TABLE public.transactions
  ADD COLUMN IF NOT EXISTS is_reverse_charge   BOOLEAN     NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS supply_type         TEXT        NOT NULL DEFAULT 'taxable'
      CHECK (supply_type IN ('taxable','zero_rated','nil_rated','exempt','non_gst')),
  ADD COLUMN IF NOT EXISTS invoice_type        TEXT        NOT NULL DEFAULT 'Regular'
      CHECK (invoice_type IN ('Regular','SEZ_with_payment','SEZ_without_payment','Deemed_export')),
  ADD COLUMN IF NOT EXISTS original_invoice_id UUID        REFERENCES public.transactions(id),
  ADD COLUMN IF NOT EXISTS cess_paise          BIGINT      NOT NULL DEFAULT 0,
  -- Derived classification — populated by InvoiceClassifier
  ADD COLUMN IF NOT EXISTS gst_invoice_category TEXT
      CHECK (gst_invoice_category IN (
          'B2B','B2CS','B2CL','CDNR','CDNA','EXP_WP','EXP_WOP',
          'AT','TXP','CDNUR','NIL_EXEMPT'
      ));

ALTER TABLE public.transaction_lines
  ADD COLUMN IF NOT EXISTS cess_paise BIGINT NOT NULL DEFAULT 0;

-- ─── 2. HSN Master ───────────────────────────────────────────────────────────
-- CGST Rule 46(h): HSN mandatory on tax invoices above turnover threshold

CREATE TABLE IF NOT EXISTS public.hsn_master (
  hsn_code        TEXT        PRIMARY KEY,
  description     TEXT        NOT NULL,
  gst_rate_pct    NUMERIC(5,2),           -- NULL = multiple rates possible
  hsn_type        TEXT        NOT NULL CHECK (hsn_type IN ('goods','services')),
  uqc             TEXT        NOT NULL DEFAULT 'NOS',  -- unit quantity code
  is_active       BOOLEAN     NOT NULL DEFAULT true,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── 3. GSTR-1 Return ────────────────────────────────────────────────────────
-- CGST Act Section 37 — outward supplies return

CREATE TABLE IF NOT EXISTS public.gstr1_returns (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  period          TEXT        NOT NULL,   -- MMYYYY e.g. "052025"
  gstin           TEXT        NOT NULL,
  payload_json    JSONB,                  -- GSTN-compatible JSON
  summary_json    JSONB,                  -- human-readable summary for CA review
  validation_errors JSONB     NOT NULL DEFAULT '[]',
  status          TEXT        NOT NULL DEFAULT 'draft'
      CHECK (status IN ('draft','validated','ca_approved','submitted')),
  validated_at    TIMESTAMPTZ,
  ca_approved_by  UUID        REFERENCES public.users(id),
  ca_approved_at  TIMESTAMPTZ,
  submitted_at    TIMESTAMPTZ,
  arn             TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr1_returns_client_period
  ON public.gstr1_returns (client_id, period);

-- ─── 4. GSTR-3B Return ───────────────────────────────────────────────────────
-- CGST Act Section 39 — summary return

CREATE TABLE IF NOT EXISTS public.gstr3b_returns (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  period          TEXT        NOT NULL,   -- MMYYYY

  -- Table 3.1: Outward taxable supplies
  outward_taxable_igst_paise  BIGINT NOT NULL DEFAULT 0,
  outward_taxable_cgst_paise  BIGINT NOT NULL DEFAULT 0,
  outward_taxable_sgst_paise  BIGINT NOT NULL DEFAULT 0,
  outward_zero_rated_paise    BIGINT NOT NULL DEFAULT 0,
  outward_nil_exempt_paise    BIGINT NOT NULL DEFAULT 0,

  -- Table 3.2: Reverse charge inward supplies
  rcm_igst_paise  BIGINT NOT NULL DEFAULT 0,
  rcm_cgst_paise  BIGINT NOT NULL DEFAULT 0,
  rcm_sgst_paise  BIGINT NOT NULL DEFAULT 0,

  -- Table 4: ITC available (CGST Rule 36(4) applied)
  itc_igst_paise  BIGINT NOT NULL DEFAULT 0,
  itc_cgst_paise  BIGINT NOT NULL DEFAULT 0,
  itc_sgst_paise  BIGINT NOT NULL DEFAULT 0,

  -- ITC caps and reversals
  itc_book_igst_paise   BIGINT NOT NULL DEFAULT 0,  -- from purchase invoices
  itc_2a_igst_paise     BIGINT NOT NULL DEFAULT 0,  -- from gstr2a_records
  itc_book_cgst_paise   BIGINT NOT NULL DEFAULT 0,
  itc_2a_cgst_paise     BIGINT NOT NULL DEFAULT 0,
  itc_book_sgst_paise   BIGINT NOT NULL DEFAULT 0,
  itc_2a_sgst_paise     BIGINT NOT NULL DEFAULT 0,

  -- Table 6: Net tax payable
  net_igst_paise  BIGINT NOT NULL DEFAULT 0,
  net_cgst_paise  BIGINT NOT NULL DEFAULT 0,
  net_sgst_paise  BIGINT NOT NULL DEFAULT 0,

  payload_json    JSONB,
  validation_errors JSONB NOT NULL DEFAULT '[]',
  status          TEXT NOT NULL DEFAULT 'draft'
      CHECK (status IN ('draft','validated','ca_approved','submitted')),
  validated_at    TIMESTAMPTZ,
  ca_approved_by  UUID REFERENCES public.users(id),
  ca_approved_at  TIMESTAMPTZ,
  submitted_at    TIMESTAMPTZ,
  arn             TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, period)
);

CREATE INDEX IF NOT EXISTS idx_gstr3b_returns_client_period
  ON public.gstr3b_returns (client_id, period);

-- ─── 5. GST Challans ─────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.gst_challans (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  period          TEXT        NOT NULL,
  cpin            TEXT,                  -- challan reference from GST portal
  igst_paise      BIGINT      NOT NULL DEFAULT 0,
  cgst_paise      BIGINT      NOT NULL DEFAULT 0,
  sgst_paise      BIGINT      NOT NULL DEFAULT 0,
  cess_paise      BIGINT      NOT NULL DEFAULT 0,
  interest_paise  BIGINT      NOT NULL DEFAULT 0,
  late_fee_paise  BIGINT      NOT NULL DEFAULT 0,
  payment_date    DATE,
  status          TEXT        NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending','paid','failed')),
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ─── 6. RLS Policies ─────────────────────────────────────────────────────────

ALTER TABLE public.hsn_master ENABLE ROW LEVEL SECURITY;
CREATE POLICY "public_read_hsn" ON public.hsn_master
  FOR SELECT TO authenticated USING (true);

ALTER TABLE public.gstr1_returns ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_gstr1" ON public.gstr1_returns
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

ALTER TABLE public.gstr3b_returns ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_gstr3b" ON public.gstr3b_returns
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

ALTER TABLE public.gst_challans ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_gst_challans" ON public.gst_challans
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- ─── 7. HSN/SAC Master Seed Data ─────────────────────────────────────────────
-- Common service SAC codes (Section 9 of CGST Act — schedule of services)

INSERT INTO public.hsn_master (hsn_code, description, gst_rate_pct, hsn_type, uqc) VALUES
  -- Professional & Advisory Services (SAC 998)
  ('998211', 'Accounting and bookkeeping services',          18.00, 'services', 'OTH'),
  ('998212', 'Financial auditing services',                  18.00, 'services', 'OTH'),
  ('998213', 'Taxation services',                            18.00, 'services', 'OTH'),
  ('998214', 'Insolvency and receivership services',         18.00, 'services', 'OTH'),
  ('998215', 'Other accounting services',                    18.00, 'services', 'OTH'),
  ('998221', 'Financial advisory services',                  18.00, 'services', 'OTH'),
  ('998222', 'Investment advisory services',                 18.00, 'services', 'OTH'),
  ('998231', 'Business advisory and management consulting',  18.00, 'services', 'OTH'),
  ('998311', 'Legal advisory and representation services',   18.00, 'services', 'OTH'),
  ('998312', 'Legal documentation and certification',        18.00, 'services', 'OTH'),
  ('998313', 'Arbitration and conciliation services',        18.00, 'services', 'OTH'),
  ('998321', 'Company secretary services',                   18.00, 'services', 'OTH'),
  -- IT Services (SAC 998)
  ('998311', 'Software development services',                18.00, 'services', 'OTH'),
  ('998312', 'IT consulting services',                       18.00, 'services', 'OTH'),
  ('998314', 'IT infrastructure and network management',     18.00, 'services', 'OTH'),
  ('998315', 'Data processing and hosting services',         18.00, 'services', 'OTH'),
  -- Banking & Finance (SAC 997)
  ('997111', 'Central banking services',                     NULL,  'services', 'OTH'),
  ('997119', 'Other banking services',                       18.00, 'services', 'OTH'),
  ('997120', 'Financial leasing services',                   18.00, 'services', 'OTH'),
  ('997131', 'Life insurance services',                      NULL,  'services', 'OTH'),
  ('997132', 'Accident and health insurance services',       18.00, 'services', 'OTH'),
  ('997133', 'Motor vehicle insurance services',             18.00, 'services', 'OTH'),
  ('997134', 'Marine, aviation and transport insurance',     18.00, 'services', 'OTH'),
  -- Real Estate (SAC 997)
  ('997211', 'Rental or leasing of residential property',    NULL,  'services', 'OTH'),
  ('997212', 'Rental or leasing of commercial property',     18.00, 'services', 'OTH'),
  ('997213', 'Trade of commercial property',                 12.00, 'services', 'OTH'),
  -- Rental of Equipment
  ('997319', 'Leasing or rental of other machinery',         18.00, 'services', 'OTH'),
  -- Common Goods HSN
  ('8471',   'Computers, laptops and peripherals',           18.00, 'goods',    'NOS'),
  ('8473',   'Computer parts and accessories',               18.00, 'goods',    'NOS'),
  ('8517',   'Mobile phones and communication equipment',    18.00, 'goods',    'NOS'),
  ('8528',   'Monitors and projectors',                      18.00, 'goods',    'NOS'),
  ('4901',   'Printed books',                                 0.00, 'goods',    'NOS'),
  ('4820',   'Diaries, notebooks, stationery',               12.00, 'goods',    'NOS'),
  ('9401',   'Office chairs and furniture',                  18.00, 'goods',    'NOS'),
  ('8443',   'Printers, photocopiers',                       18.00, 'goods',    'NOS'),
  ('3926',   'Plastic stationery items',                     18.00, 'goods',    'NOS'),
  ('7102',   'Diamonds',                                      0.00, 'goods',    'NOS'),
  ('7108',   'Gold',                                          3.00, 'goods',    'GMS')
ON CONFLICT (hsn_code) DO NOTHING;

-- ─── 8. Updated_at trigger for new tables ─────────────────────────────────────

CREATE OR REPLACE FUNCTION public.update_updated_at()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$;

DROP TRIGGER IF EXISTS trg_gstr1_updated_at ON public.gstr1_returns;
CREATE TRIGGER trg_gstr1_updated_at
  BEFORE UPDATE ON public.gstr1_returns
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

DROP TRIGGER IF EXISTS trg_gstr3b_updated_at ON public.gstr3b_returns;
CREATE TRIGGER trg_gstr3b_updated_at
  BEFORE UPDATE ON public.gstr3b_returns
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

DROP TRIGGER IF EXISTS trg_gst_challans_updated_at ON public.gst_challans;
CREATE TRIGGER trg_gst_challans_updated_at
  BEFORE UPDATE ON public.gst_challans
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
