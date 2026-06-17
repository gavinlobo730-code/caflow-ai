-- PracticeSync AI — Migration 093: Payroll / Fixed-Assets / Banking foundation
-- MODERNIZED replacement for the never-applied Migration 054, rewritten for the
-- post-057 architecture (one firm → one firm-scoped master CoA; client_id
-- deprecated for CoA; no `is_system` column; CoA seeded per-firm by
-- coa_seed_service whose names match phase2_journal_service._find_account).
--
-- Idempotent and safe to re-run. No firm_id=NULL templates. No `is_system`.
-- All monetary values integer paise. GST/ITR logic unchanged (CGST/IT Act).
--
-- ════════════════════════════════════════════════════════════════════════════
-- SECTION 1 — Backfill payroll & fixed-asset CoA accounts (FIRM-SCOPED)
-- ════════════════════════════════════════════════════════════════════════════
-- The posting engine resolves accounts by NAME via ILIKE patterns
-- (phase2_journal_service._find_account). Existing firms seeded before the fuller
-- master chart may lack accounts whose NAME matches those patterns, which makes
-- journal_for_payroll / _depreciation / _asset_* fail. This inserts each required
-- account for a firm ONLY when (a) the firm already has a CoA, (b) no account
-- whose name matches the engine pattern exists, and (c) the target code is free.
-- => no duplicates, no code collisions, fully idempotent.

INSERT INTO public.chart_of_accounts
  (firm_id, client_id, account_code, account_name, account_type, account_subtype, is_active)
SELECT f.id, NULL, req.code, req.name, req.type, req.subtype, true
FROM public.firms f
CROSS JOIN (VALUES
  -- name                        code     type         subtype             match-pattern
  ('Salaries Expense',          '5020', 'Expense',   'Payroll',           '%salaries expense%'),
  ('Depreciation Expense',      '5021', 'Expense',   'Depreciation',      '%depreciation expense%'),
  ('PF Payable',                '2310', 'Liability', 'Current Liability', '%pf payable%'),
  ('ESI Payable',               '2311', 'Liability', 'Current Liability', '%esi payable%'),
  ('PT Payable',                '2312', 'Liability', 'Current Liability', '%pt payable%'),
  ('TDS Payable - Salary',      '2313', 'Liability', 'Current Liability', '%tds payable - salary%'),
  ('Net Salary Payable',        '2314', 'Liability', 'Current Liability', '%net salary payable%'),
  ('Plant & Machinery',         '1530', 'Asset',     'Fixed Asset',       '%plant & machinery%'),
  ('Computers & Software',      '1531', 'Asset',     'Fixed Asset',       '%computers & software%'),
  ('Vehicles',                  '1532', 'Asset',     'Fixed Asset',       '%vehicles%'),
  ('Land & Building',           '1533', 'Asset',     'Fixed Asset',       '%land & building%'),
  ('Intangible Assets',         '1534', 'Asset',     'Fixed Asset',       '%intangible assets%'),
  ('Furniture & Fixtures',      '1535', 'Asset',     'Fixed Asset',       '%furniture & fixtures%'),
  ('Accumulated Depreciation',  '1590', 'Asset',     'Fixed Asset',       '%accumulated depreciation%'),
  ('Profit on Asset Disposal',  '4910', 'Revenue',   'Other Income',      '%profit on asset disposal%'),
  ('Loss on Asset Disposal',    '5910', 'Expense',   'Other Expense',     '%loss on asset disposal%')
) AS req(name, code, type, subtype, pattern)
WHERE EXISTS (SELECT 1 FROM public.chart_of_accounts c0 WHERE c0.firm_id = f.id)
  AND NOT EXISTS (
        SELECT 1 FROM public.chart_of_accounts c
        WHERE c.firm_id = f.id AND c.account_name ILIKE req.pattern)
  AND NOT EXISTS (
        SELECT 1 FROM public.chart_of_accounts c
        WHERE c.firm_id = f.id AND c.account_code = req.code);

-- ════════════════════════════════════════════════════════════════════════════
-- SECTION 2 — payroll_employees: helper columns (all ADD IF NOT EXISTS)
-- ════════════════════════════════════════════════════════════════════════════
ALTER TABLE public.payroll_employees
  ADD COLUMN IF NOT EXISTS aadhaar_last4            TEXT,
  ADD COLUMN IF NOT EXISTS uan                      TEXT,
  ADD COLUMN IF NOT EXISTS esi_number               TEXT,
  ADD COLUMN IF NOT EXISTS department               TEXT,
  ADD COLUMN IF NOT EXISTS joining_date             DATE,
  ADD COLUMN IF NOT EXISTS bank_account_no          TEXT,
  ADD COLUMN IF NOT EXISTS bank_ifsc                TEXT,
  ADD COLUMN IF NOT EXISTS bank_name                TEXT,
  ADD COLUMN IF NOT EXISTS city                     TEXT,
  ADD COLUMN IF NOT EXISTS state                    TEXT,
  ADD COLUMN IF NOT EXISTS lta_paise                BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS medical_paise            BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS special_allowance_paise  BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS pt_applicable            BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS pt_state                 TEXT,
  ADD COLUMN IF NOT EXISTS status                   TEXT NOT NULL DEFAULT 'active';
-- Named CHECK added separately and guarded so re-runs don't error.
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'payroll_employees_status_check') THEN
    ALTER TABLE public.payroll_employees
      ADD CONSTRAINT payroll_employees_status_check
      CHECK (status IN ('active','resigned','terminated'));
  END IF;
END $$;

-- ════════════════════════════════════════════════════════════════════════════
-- SECTION 3 — payroll_runs: journal link, totals, status (READ by journal_for_payroll)
-- ════════════════════════════════════════════════════════════════════════════
ALTER TABLE public.payroll_runs
  ADD COLUMN IF NOT EXISTS journal_entry_id   UUID REFERENCES public.journal_entries(id),
  ADD COLUMN IF NOT EXISTS finalized_at       TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS total_gross_paise  BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_net_paise    BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_pf_paise     BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_esi_paise    BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_pt_paise     BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_tds_paise    BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS headcount          INTEGER NOT NULL DEFAULT 0;

-- Widen status to allow 'review' (current CHECK is draft/finalized). No existing
-- row violates the wider set, so this is safe.
ALTER TABLE public.payroll_runs DROP CONSTRAINT IF EXISTS payroll_runs_status_check;
ALTER TABLE public.payroll_runs
  ADD CONSTRAINT payroll_runs_status_check CHECK (status IN ('draft','review','finalized'));

-- ════════════════════════════════════════════════════════════════════════════
-- SECTION 4 — payroll_slips: employer-side PF/ESI and attendance
-- ════════════════════════════════════════════════════════════════════════════
ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS pf_employer_paise   BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS esi_employer_paise  BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS lop_days            INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS working_days        INTEGER NOT NULL DEFAULT 26,
  ADD COLUMN IF NOT EXISTS days_present        INTEGER NOT NULL DEFAULT 26;

-- ════════════════════════════════════════════════════════════════════════════
-- SECTION 5 — fixed_assets: depreciation tracking + acquisition journal link
-- ════════════════════════════════════════════════════════════════════════════
ALTER TABLE public.fixed_assets
  ADD COLUMN IF NOT EXISTS depreciation_posted_through DATE,
  ADD COLUMN IF NOT EXISTS current_wdv_paise           BIGINT,
  ADD COLUMN IF NOT EXISTS asset_code                  TEXT,
  ADD COLUMN IF NOT EXISTS location                    TEXT,
  ADD COLUMN IF NOT EXISTS journal_entry_id            UUID REFERENCES public.journal_entries(id);

-- ════════════════════════════════════════════════════════════════════════════
-- SECTION 6 — bank_accounts (new table)
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS public.bank_accounts (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id               UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id             UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  bank_name             TEXT NOT NULL,
  account_no            TEXT NOT NULL,
  ifsc                  TEXT,
  account_type          TEXT NOT NULL DEFAULT 'Current'
                          CHECK (account_type IN ('Current','Savings','Cash Credit','Overdraft')),
  opening_balance_paise BIGINT NOT NULL DEFAULT 0,
  opening_balance_date  DATE,
  coa_account_id        UUID REFERENCES public.chart_of_accounts(id),
  is_active             BOOLEAN NOT NULL DEFAULT true,
  created_at            TIMESTAMPTZ DEFAULT now(),
  UNIQUE (client_id, account_no)
);
ALTER TABLE public.bank_accounts ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_manage_bank_accounts" ON public.bank_accounts;
CREATE POLICY "firm_staff_manage_bank_accounts" ON public.bank_accounts
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.bank_accounts TO authenticated;

-- ════════════════════════════════════════════════════════════════════════════
-- SECTION 7 — bank_statements: link to bank_accounts
-- ════════════════════════════════════════════════════════════════════════════
ALTER TABLE public.bank_statements
  ADD COLUMN IF NOT EXISTS bank_account_id UUID REFERENCES public.bank_accounts(id);

-- ════════════════════════════════════════════════════════════════════════════
-- SECTION 8 — salary_structures (new table)
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS public.salary_structures (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id       UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  name            TEXT NOT NULL,
  basic_percent   NUMERIC(5,2) NOT NULL DEFAULT 40.00,
  hra_percent     NUMERIC(5,2) NOT NULL DEFAULT 20.00,
  da_percent      NUMERIC(5,2) NOT NULL DEFAULT 0.00,
  lta_percent     NUMERIC(5,2) NOT NULL DEFAULT 5.00,
  medical_paise   BIGINT NOT NULL DEFAULT 125000,
  special_percent NUMERIC(5,2) NOT NULL DEFAULT 0.00,
  pf_applicable   BOOLEAN NOT NULL DEFAULT true,
  esi_applicable  BOOLEAN NOT NULL DEFAULT true,
  pt_applicable   BOOLEAN NOT NULL DEFAULT false,
  pt_state        TEXT,
  created_at      TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.salary_structures ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_manage_salary_structures" ON public.salary_structures;
CREATE POLICY "firm_staff_manage_salary_structures" ON public.salary_structures
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.salary_structures TO authenticated;

-- ════════════════════════════════════════════════════════════════════════════
-- SECTION 9 — bank_matching_rules (new table)
-- ════════════════════════════════════════════════════════════════════════════
CREATE TABLE IF NOT EXISTS public.bank_matching_rules (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id              UUID NOT NULL REFERENCES public.firms(id)   ON DELETE CASCADE,
  client_id            UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  rule_name            TEXT NOT NULL,
  description_pattern  TEXT,
  amount_min_paise     BIGINT,
  amount_max_paise     BIGINT,
  txn_type             TEXT CHECK (txn_type IN ('debit','credit','any')) DEFAULT 'any',
  suggested_account_id UUID REFERENCES public.chart_of_accounts(id),
  suggested_narration  TEXT,
  is_active            BOOLEAN NOT NULL DEFAULT true,
  created_at           TIMESTAMPTZ DEFAULT now()
);
ALTER TABLE public.bank_matching_rules ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_staff_manage_bank_rules" ON public.bank_matching_rules;
CREATE POLICY "firm_staff_manage_bank_rules" ON public.bank_matching_rules
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.bank_matching_rules TO authenticated;
