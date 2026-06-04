-- Migration 038: MCA schema fixes and enhancements
-- Companies Act 2013:
--   Section 92  — Annual Return (Form MGT-7)
--   Section 137 — Annual Financial Statement (Form AOC-4)
--   Section 139 — Auditor Appointment (Form ADT-1)
--   Section 165 — Director KYC (Form DIR-3 KYC)

-- ─── 1. Fix mca_filings column name and add missing columns ──────────────────

-- Add company_cin as alias (old inserts used company_cin, DB had cin)
ALTER TABLE public.mca_filings
  ADD COLUMN IF NOT EXISTS company_cin TEXT,  -- populated from cin below
  ADD COLUMN IF NOT EXISTS period       TEXT,  -- e.g. "FY 2025-26"
  ADD COLUMN IF NOT EXISTS srn          TEXT,  -- Service Request Number
  ADD COLUMN IF NOT EXISTS agm_date     DATE,  -- AGM date drives AOC-4/MGT-7 deadline
  ADD COLUMN IF NOT EXISTS financial_year TEXT, -- "2024-25"
  ADD COLUMN IF NOT EXISTS auditor_name  TEXT,
  ADD COLUMN IF NOT EXISTS auditor_din   TEXT,
  ADD COLUMN IF NOT EXISTS total_paise   BIGINT DEFAULT 0;  -- fee paid paise

-- Sync company_cin ← cin for backward compat
UPDATE public.mca_filings SET company_cin = cin WHERE company_cin IS NULL AND cin IS NOT NULL;

-- Normalise status to lowercase
UPDATE public.mca_filings SET status = LOWER(status);

-- Drop old case-sensitive check and add lowercase-only check
ALTER TABLE public.mca_filings DROP CONSTRAINT IF EXISTS mca_filings_status_check;
ALTER TABLE public.mca_filings
  ADD CONSTRAINT mca_filings_status_check
  CHECK (status IN ('pending','filed','overdue','in_progress','not_applicable'));

-- ─── 2. MCA Directors table (DIR-3 KYC) ──────────────────────────────────────
-- Companies Act Section 165 — Director KYC due 30 Sep each year

CREATE TABLE IF NOT EXISTS public.mca_directors (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id           UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id         UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  director_name     TEXT        NOT NULL,
  din               TEXT        NOT NULL,   -- Director Identification Number (8 digits)
  pan               TEXT,                   -- PAN for TDS/Income Tax cross-reference
  designation       TEXT        NOT NULL DEFAULT 'Director',  -- Director, MD, WTD, etc.
  date_of_appointment DATE,
  date_of_cessation  DATE,                  -- NULL = still active
  -- Contact details for DIR-3 KYC
  email             TEXT,
  mobile            TEXT,
  address           TEXT,
  -- KYC tracking
  kyc_status        TEXT        NOT NULL DEFAULT 'pending'
      CHECK (kyc_status IN ('pending','filed','overdue','deactivated')),
  kyc_due_date      DATE,                   -- 30 Sep of current year
  kyc_filed_date    DATE,
  kyc_srn           TEXT,                   -- SRN from MCA portal
  is_active         BOOLEAN     NOT NULL DEFAULT true,
  notes             TEXT,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, din)
);

CREATE INDEX IF NOT EXISTS idx_mca_directors_client ON public.mca_directors (client_id);

-- ─── 3. MCA Companies master ──────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.mca_companies (
  id                UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id           UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id         UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  cin               TEXT        NOT NULL,   -- Corporate Identity Number
  company_name      TEXT        NOT NULL,
  incorp_date       DATE,
  registered_office TEXT,
  company_category  TEXT        NOT NULL DEFAULT 'Private Limited'
      CHECK (company_category IN ('Private Limited','Public Limited','OPC','LLP','Section 8','Nidhi')),
  authorized_capital_paise  BIGINT NOT NULL DEFAULT 0,
  paid_up_capital_paise     BIGINT NOT NULL DEFAULT 0,
  agm_due_date      DATE,                   -- 30 Sep for private companies
  last_agm_date     DATE,
  last_agm_year     TEXT,                   -- "2024-25"
  roc_jurisdiction  TEXT,
  email             TEXT,
  is_active         BOOLEAN NOT NULL DEFAULT true,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (client_id, cin)
);

CREATE INDEX IF NOT EXISTS idx_mca_companies_client ON public.mca_companies (client_id);

-- ─── 4. RLS ───────────────────────────────────────────────────────────────────

ALTER TABLE public.mca_directors ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_mca_directors" ON public.mca_directors;
CREATE POLICY "firm_staff_mca_directors" ON public.mca_directors
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

ALTER TABLE public.mca_companies ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_mca_companies" ON public.mca_companies;
CREATE POLICY "firm_staff_mca_companies" ON public.mca_companies
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

-- ─── 5. Updated_at triggers ──────────────────────────────────────────────────

DROP TRIGGER IF EXISTS trg_mca_directors_updated_at ON public.mca_directors;
CREATE TRIGGER trg_mca_directors_updated_at
  BEFORE UPDATE ON public.mca_directors
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();

DROP TRIGGER IF EXISTS trg_mca_companies_updated_at ON public.mca_companies;
CREATE TRIGGER trg_mca_companies_updated_at
  BEFORE UPDATE ON public.mca_companies
  FOR EACH ROW EXECUTE FUNCTION public.update_updated_at();
