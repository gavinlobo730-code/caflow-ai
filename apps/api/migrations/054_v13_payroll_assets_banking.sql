-- V1.3 Foundation Migration
-- Adds missing COA accounts for Payroll, Fixed Assets, and Banking modules
-- Also adds helper columns for depreciation tracking and bank accounts

-- ─── 1. MISSING CHART OF ACCOUNTS (template firm) ────────────────────────────
-- These are seeded at the template level (firm_id = NULL means global template)
-- Phase2JournalService will look these up by name pattern

INSERT INTO public.chart_of_accounts (firm_id, client_id, account_code, account_name, account_type, account_subtype, is_system)
VALUES
  -- Payroll expense accounts
  (NULL, NULL, '5010', 'Salaries Expense',             'Expense',   'Payroll',    true),
  (NULL, NULL, '5011', 'PF Expense',                   'Expense',   'Payroll',    true),
  (NULL, NULL, '5012', 'ESI Expense',                  'Expense',   'Payroll',    true),

  -- Payroll liability accounts
  (NULL, NULL, '2302', 'PF Payable',                   'Liability', 'Payable',    true),
  (NULL, NULL, '2303', 'ESI Payable',                  'Liability', 'Payable',    true),
  (NULL, NULL, '2304', 'PT Payable',                   'Liability', 'Payable',    true),
  (NULL, NULL, '2305', 'TDS Payable - Salary (24Q)',   'Liability', 'Payable',    true),
  (NULL, NULL, '2306', 'Net Salary Payable',            'Liability', 'Payable',    true),

  -- Fixed asset accounts
  (NULL, NULL, '1510', 'Plant & Machinery',            'Asset',     'Fixed Asset', true),
  (NULL, NULL, '1511', 'Furniture & Fixtures',         'Asset',     'Fixed Asset', true),
  (NULL, NULL, '1512', 'Computers & Software',         'Asset',     'Fixed Asset', true),
  (NULL, NULL, '1513', 'Vehicles',                     'Asset',     'Fixed Asset', true),
  (NULL, NULL, '1514', 'Land & Building',              'Asset',     'Fixed Asset', true),
  (NULL, NULL, '1515', 'Intangible Assets',            'Asset',     'Fixed Asset', true),
  (NULL, NULL, '1520', 'Accumulated Depreciation',     'Asset',     'Contra Asset', true),
  (NULL, NULL, '5014', 'Depreciation Expense',         'Expense',   'Depreciation', true),
  (NULL, NULL, '6001', 'Profit on Asset Disposal',     'Income',    'Other Income', true),
  (NULL, NULL, '7001', 'Loss on Asset Disposal',       'Expense',   'Other Expense', true)
ON CONFLICT (account_code, firm_id, client_id)
  DO NOTHING;

-- ─── 2. PAYROLL EMPLOYEES — add missing columns ───────────────────────────────
ALTER TABLE public.payroll_employees
  ADD COLUMN IF NOT EXISTS aadhaar_last4       TEXT,          -- masked, last 4 digits only
  ADD COLUMN IF NOT EXISTS uan                 TEXT,          -- Universal Account Number (PF)
  ADD COLUMN IF NOT EXISTS esi_number          TEXT,
  ADD COLUMN IF NOT EXISTS department          TEXT,
  ADD COLUMN IF NOT EXISTS joining_date        DATE,
  ADD COLUMN IF NOT EXISTS bank_account_no     TEXT,
  ADD COLUMN IF NOT EXISTS bank_ifsc           TEXT,
  ADD COLUMN IF NOT EXISTS bank_name           TEXT,
  ADD COLUMN IF NOT EXISTS city                TEXT,
  ADD COLUMN IF NOT EXISTS state               TEXT,
  ADD COLUMN IF NOT EXISTS lta_paise           BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS medical_paise       BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS special_allowance_paise BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS pt_applicable       BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS pt_state            TEXT,          -- state code for PT slab lookup
  ADD COLUMN IF NOT EXISTS status              TEXT NOT NULL DEFAULT 'active'
                                               CHECK (status IN ('active','resigned','terminated'));

-- ─── 3. PAYROLL RUNS — add journal reference and review status ────────────────
ALTER TABLE public.payroll_runs
  ADD COLUMN IF NOT EXISTS journal_entry_id    UUID REFERENCES public.journal_entries(id),
  ADD COLUMN IF NOT EXISTS finalized_at        TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS total_gross_paise   BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_net_paise     BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_pf_paise      BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_esi_paise     BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_pt_paise      BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_tds_paise     BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS headcount           INTEGER NOT NULL DEFAULT 0;

-- Status: add 'review' state
ALTER TABLE public.payroll_runs
  DROP CONSTRAINT IF EXISTS payroll_runs_status_check;
ALTER TABLE public.payroll_runs
  ADD CONSTRAINT payroll_runs_status_check
  CHECK (status IN ('draft', 'review', 'finalized'));

-- ─── 4. PAYROLL SLIPS — add employer-side PF/ESI ─────────────────────────────
ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS pf_employer_paise   BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS esi_employer_paise  BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS lop_days            INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS working_days        INTEGER NOT NULL DEFAULT 26,
  ADD COLUMN IF NOT EXISTS days_present        INTEGER NOT NULL DEFAULT 26;

-- ─── 5. FIXED ASSETS — add depreciation tracking date ────────────────────────
ALTER TABLE public.fixed_assets
  ADD COLUMN IF NOT EXISTS depreciation_posted_through DATE,  -- last period depreciation was posted
  ADD COLUMN IF NOT EXISTS current_wdv_paise   BIGINT,        -- computed WDV after accumulated depn
  ADD COLUMN IF NOT EXISTS asset_code          TEXT,          -- e.g. FA-001
  ADD COLUMN IF NOT EXISTS location            TEXT,
  ADD COLUMN IF NOT EXISTS journal_entry_id    UUID REFERENCES public.journal_entries(id);  -- acquisition journal

-- ─── 6. BANK ACCOUNTS TABLE (separate from bank_statements) ──────────────────
CREATE TABLE IF NOT EXISTS public.bank_accounts (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  bank_name       TEXT NOT NULL,
  account_no      TEXT NOT NULL,
  ifsc            TEXT,
  account_type    TEXT NOT NULL DEFAULT 'Current'
                  CHECK (account_type IN ('Current', 'Savings', 'Cash Credit', 'Overdraft')),
  opening_balance_paise BIGINT NOT NULL DEFAULT 0,
  opening_balance_date  DATE,
  coa_account_id  UUID REFERENCES public.chart_of_accounts(id),  -- linked GL account
  is_active       BOOLEAN NOT NULL DEFAULT true,
  created_at      TIMESTAMPTZ DEFAULT now(),
  UNIQUE(client_id, account_no)
);

ALTER TABLE public.bank_accounts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_manage_bank_accounts" ON public.bank_accounts
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.bank_accounts TO authenticated;

-- ─── 7. BANK STATEMENTS — link to bank_accounts table ────────────────────────
ALTER TABLE public.bank_statements
  ADD COLUMN IF NOT EXISTS bank_account_id UUID REFERENCES public.bank_accounts(id);

-- ─── 8. SALARY STRUCTURES (reusable templates) ───────────────────────────────
CREATE TABLE IF NOT EXISTS public.salary_structures (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  basic_percent   NUMERIC(5,2) NOT NULL DEFAULT 40.00,  -- % of CTC
  hra_percent     NUMERIC(5,2) NOT NULL DEFAULT 20.00,
  da_percent      NUMERIC(5,2) NOT NULL DEFAULT 0.00,
  lta_percent     NUMERIC(5,2) NOT NULL DEFAULT 5.00,
  medical_paise   BIGINT NOT NULL DEFAULT 125000,  -- ₹1250/month
  special_percent NUMERIC(5,2) NOT NULL DEFAULT 0.00,  -- remainder
  pf_applicable   BOOLEAN NOT NULL DEFAULT true,
  esi_applicable  BOOLEAN NOT NULL DEFAULT true,
  pt_applicable   BOOLEAN NOT NULL DEFAULT false,
  pt_state        TEXT,
  created_at      TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.salary_structures ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_manage_salary_structures" ON public.salary_structures
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.salary_structures TO authenticated;

-- ─── 9. BANK MATCHING RULES ──────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.bank_matching_rules (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  rule_name       TEXT NOT NULL,
  description_pattern TEXT,  -- ILIKE pattern matched against bank txn description
  amount_min_paise BIGINT,
  amount_max_paise BIGINT,
  txn_type        TEXT CHECK (txn_type IN ('debit', 'credit', 'any')) DEFAULT 'any',
  suggested_account_id UUID REFERENCES public.chart_of_accounts(id),
  suggested_narration TEXT,
  is_active       BOOLEAN NOT NULL DEFAULT true,
  created_at      TIMESTAMPTZ DEFAULT now()
);

ALTER TABLE public.bank_matching_rules ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_staff_manage_bank_rules" ON public.bank_matching_rules
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.bank_matching_rules TO authenticated;
