-- Migration 037: TDS Engine — 24Q/26Q filing tables
-- IT Act Section 192 (salary TDS), Section 194 (non-salary TDS)
-- All monetary values in integer paise — IT Act Section 145A
-- Backward compatible: all new columns have DEFAULT values

-- ─── 1. TDS Returns table ─────────────────────────────────────────────────────
-- Stores quarterly 24Q/26Q/27Q return filing records per client

CREATE TABLE IF NOT EXISTS public.tds_returns (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  return_type     TEXT        NOT NULL CHECK (return_type IN ('24Q','26Q','27Q','27EQ')),
  financial_year  TEXT        NOT NULL,  -- e.g. "2025-26"
  quarter         TEXT        NOT NULL CHECK (quarter IN ('Q1','Q2','Q3','Q4')),
  quarter_end     DATE        NOT NULL,  -- 30-Jun, 30-Sep, 31-Dec, 31-Mar
  due_date        DATE        NOT NULL,  -- 31-Jul, 31-Oct, 31-Jan, 31-May
  -- Aggregated figures from tds_deductions
  total_deductions_paise   BIGINT NOT NULL DEFAULT 0,
  total_deposits_paise     BIGINT NOT NULL DEFAULT 0,
  deductee_count           INT    NOT NULL DEFAULT 0,
  -- Filing status
  status          TEXT        NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending','prepared','ca_approved','filed','revised')),
  prn             TEXT,                  -- Provisional Receipt Number after filing
  ack_number      TEXT,                  -- Acknowledgement number
  filed_at        TIMESTAMPTZ,
  ca_approved_by  UUID        REFERENCES public.users(id),
  ca_approved_at  TIMESTAMPTZ,
  -- FVU / output
  fvu_json        JSONB,                 -- structured 24Q/26Q data for FVU generation
  validation_errors JSONB    NOT NULL DEFAULT '[]',
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, return_type, financial_year, quarter)
);

CREATE INDEX IF NOT EXISTS idx_tds_returns_client ON public.tds_returns (client_id, financial_year, quarter);

-- ─── 2. TDS Deductions — link challans properly ───────────────────────────────
-- Add challan_id FK to existing tds_deductions table (if column doesn't exist)

ALTER TABLE public.tds_deductions
  ADD COLUMN IF NOT EXISTS tds_return_id  UUID REFERENCES public.tds_returns(id),
  ADD COLUMN IF NOT EXISTS nature_of_payment TEXT,  -- e.g. "Salary", "Professional fees"
  ADD COLUMN IF NOT EXISTS certificate_no TEXT,     -- Form 16/16A certificate number once issued
  ADD COLUMN IF NOT EXISTS is_lower_deduction BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS lower_deduction_cert TEXT; -- Form 15G/15H or lower deduction certificate no

-- ─── 3. TDS Challans ─────────────────────────────────────────────────────────
-- Tracks Challan 281 deposits to government account

CREATE TABLE IF NOT EXISTS public.tds_challans (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  challan_no      TEXT        NOT NULL,   -- ITNS Challan 281 number
  bsr_code        TEXT        NOT NULL,   -- Bank BSR code (7 digits)
  payment_date    DATE        NOT NULL,
  financial_year  TEXT        NOT NULL,
  quarter         TEXT        NOT NULL CHECK (quarter IN ('Q1','Q2','Q3','Q4')),
  -- Tax head amounts
  tds_paise       BIGINT      NOT NULL DEFAULT 0,
  surcharge_paise BIGINT      NOT NULL DEFAULT 0,
  interest_paise  BIGINT      NOT NULL DEFAULT 0,
  penalty_paise   BIGINT      NOT NULL DEFAULT 0,
  total_paise     BIGINT      NOT NULL DEFAULT 0,
  -- Bank details
  bank_name       TEXT,
  minor_head      TEXT        NOT NULL DEFAULT '200',  -- 200=TDS on company, 400=regular
  section         TEXT,                                -- primary TDS section for this challan
  status          TEXT        NOT NULL DEFAULT 'deposited'
      CHECK (status IN ('deposited','matched','unmatched')),
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tds_challans_client ON public.tds_challans (client_id, financial_year, quarter);

-- ─── 4. TDS Certificates ─────────────────────────────────────────────────────
-- Form 16 (salary) and Form 16A (non-salary) certificate tracking

CREATE TABLE IF NOT EXISTS public.tds_certificates (
  id              UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  certificate_type TEXT       NOT NULL CHECK (certificate_type IN ('16','16A','16B','16C')),
  deductee_name   TEXT        NOT NULL,
  deductee_pan    TEXT        NOT NULL,
  financial_year  TEXT        NOT NULL,
  quarter         TEXT,                  -- NULL for annual (Form 16)
  -- Amounts (all paise)
  total_income_paise     BIGINT NOT NULL DEFAULT 0,
  tds_deducted_paise     BIGINT NOT NULL DEFAULT 0,
  tds_deposited_paise    BIGINT NOT NULL DEFAULT 0,
  -- Status
  status          TEXT        NOT NULL DEFAULT 'pending'
      CHECK (status IN ('pending','generated','issued','downloaded')),
  certificate_no  TEXT,                  -- TRACES certificate number
  generated_at    TIMESTAMPTZ,
  issued_at       TIMESTAMPTZ,
  tds_return_id   UUID        REFERENCES public.tds_returns(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_tds_certificates_client ON public.tds_certificates (client_id, deductee_pan, financial_year);

-- ─── 5. TDS Section thresholds ────────────────────────────────────────────────
-- IT Act Section 194 threshold limits for auto-validation

CREATE TABLE IF NOT EXISTS public.tds_section_limits (
  section         TEXT        PRIMARY KEY,
  description     TEXT        NOT NULL,
  threshold_paise BIGINT      NOT NULL DEFAULT 0,  -- 0 = no threshold, deduct from first rupee
  rate_individual NUMERIC(5,2) NOT NULL,
  rate_company    NUMERIC(5,2) NOT NULL,
  return_type     TEXT        NOT NULL CHECK (return_type IN ('24Q','26Q','27Q','27EQ')),
  is_active       BOOLEAN     NOT NULL DEFAULT true
);

INSERT INTO public.tds_section_limits (section, description, threshold_paise, rate_individual, rate_company, return_type) VALUES
  ('192',  'Salary',                                     0,          0,    0,   '24Q'),
  ('193',  'Interest on securities',                     1000_00,   10,   10,   '26Q'),
  ('194',  'Dividends',                                  5000_00,   10,   10,   '26Q'),
  ('194A', 'Interest other than securities (bank)',      4000_00,   10,   10,   '26Q'),
  ('194B', 'Winnings from lottery',                      10000_00,  30,   30,   '26Q'),
  ('194C', 'Contractor payment (single)',                30000_00,   1,    2,   '26Q'),
  ('194C', 'Contractor payment (aggregate annual)',      100000_00,  1,    2,   '26Q'),
  ('194D', 'Insurance commission',                       15000_00,   5,   10,   '26Q'),
  ('194G', 'Commission on sale of lottery tickets',      15000_00,   5,    5,   '26Q'),
  ('194H', 'Commission or brokerage',                    15000_00,   5,    5,   '26Q'),
  ('194I', 'Rent (land, building, furniture)',           240000_00, 10,   10,   '26Q'),
  ('194J', 'Professional or technical fees',             30000_00,  10,   10,   '26Q'),
  ('194K', 'Income from units of mutual fund',           5000_00,   10,   10,   '26Q'),
  ('194LA','Compensation on acquisition of property',    250000_00, 10,   10,   '26Q'),
  ('194Q', 'Purchase of goods',                          5000000_00, 0.1,  0.1, '26Q'),
  ('206C', 'TCS — Sale of goods',                       0,          0.1,  0.1, '27EQ')
ON CONFLICT (section) DO NOTHING;

-- ─── 6. RLS Policies ─────────────────────────────────────────────────────────

ALTER TABLE public.tds_returns ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_tds_returns" ON public.tds_returns;
CREATE POLICY "firm_staff_tds_returns" ON public.tds_returns
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

ALTER TABLE public.tds_challans ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_tds_challans" ON public.tds_challans;
CREATE POLICY "firm_staff_tds_challans" ON public.tds_challans
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

ALTER TABLE public.tds_certificates ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_tds_certificates" ON public.tds_certificates;
CREATE POLICY "firm_staff_tds_certificates" ON public.tds_certificates
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

ALTER TABLE public.tds_section_limits ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "public_read_tds_limits" ON public.tds_section_limits;
CREATE POLICY "public_read_tds_limits" ON public.tds_section_limits
  FOR SELECT TO authenticated USING (true);

-- ─── 7. Updated_at triggers ───────────────────────────────────────────────────

DROP TRIGGER IF EXISTS trg_tds_returns_updated_at ON public.tds_returns;
CREATE TRIGGER trg_tds_returns_updated_at
  BEFORE UPDATE ON public.tds_returns
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

DROP TRIGGER IF EXISTS trg_tds_challans_updated_at ON public.tds_challans;
CREATE TRIGGER trg_tds_challans_updated_at
  BEFORE UPDATE ON public.tds_challans
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

DROP TRIGGER IF EXISTS trg_tds_certificates_updated_at ON public.tds_certificates;
CREATE TRIGGER trg_tds_certificates_updated_at
  BEFORE UPDATE ON public.tds_certificates
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
