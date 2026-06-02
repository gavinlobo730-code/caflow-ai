-- ============================================================================
-- Migration 014: Complete all missing tables for CAflow production readiness
-- Run this ONCE in Supabase SQL Editor → SQL Editor → New Query → Run
-- Safe to re-run: all statements use IF NOT EXISTS / OR REPLACE
-- ============================================================================

-- ─── 0. Helper: ensure uuid extension ────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── 1. is_active on users (migration 013) ───────────────────────────────────
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS is_active BOOLEAN NOT NULL DEFAULT true;

-- ─── 2. PAYROLL ──────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.payroll_employees (
  id                      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id                 UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id               UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  name                    TEXT        NOT NULL,
  pan                     TEXT,
  designation             TEXT,
  basic_paise             BIGINT      NOT NULL DEFAULT 0,
  hra_percent             NUMERIC(5,2) NOT NULL DEFAULT 0,
  da_percent              NUMERIC(5,2) NOT NULL DEFAULT 0,
  other_allowances_paise  BIGINT      NOT NULL DEFAULT 0,
  pf_applicable           BOOLEAN     NOT NULL DEFAULT false,
  esi_applicable          BOOLEAN     NOT NULL DEFAULT false,
  is_active               BOOLEAN     NOT NULL DEFAULT true,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.payroll_runs (
  id           UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id      UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id    UUID        NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  month        TEXT        NOT NULL,  -- e.g. '2026-06'
  status       TEXT        NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','finalized')),
  generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.payroll_slips (
  id                  UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  run_id              UUID    NOT NULL REFERENCES public.payroll_runs(id) ON DELETE CASCADE,
  employee_id         UUID    NOT NULL REFERENCES public.payroll_employees(id) ON DELETE CASCADE,
  gross_paise         BIGINT  NOT NULL,
  pf_employee_paise   BIGINT  NOT NULL DEFAULT 0,
  esi_employee_paise  BIGINT  NOT NULL DEFAULT 0,
  pt_paise            BIGINT  NOT NULL DEFAULT 0,
  tds_paise           BIGINT  NOT NULL DEFAULT 0,
  net_paise           BIGINT  NOT NULL,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.payroll_employees ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payroll_runs      ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.payroll_slips     ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "payroll_employees_own_firm" ON public.payroll_employees;
CREATE POLICY "payroll_employees_own_firm" ON public.payroll_employees
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "payroll_runs_own_firm" ON public.payroll_runs;
CREATE POLICY "payroll_runs_own_firm" ON public.payroll_runs
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "payroll_slips_own_firm" ON public.payroll_slips;
CREATE POLICY "payroll_slips_own_firm" ON public.payroll_slips
  FOR ALL USING (
    run_id IN (SELECT id FROM public.payroll_runs WHERE firm_id = get_my_firm_id())
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_employees TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_runs      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.payroll_slips     TO authenticated;

-- ─── 3. FEE BILLING ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.fee_engagements (
  id            UUID  PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id       UUID  NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id     UUID  NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  service_type  TEXT  NOT NULL,  -- e.g. 'GST Filing', 'ITR Filing', 'Accounting'
  fee_paise     BIGINT NOT NULL DEFAULT 0,
  billing_cycle TEXT  NOT NULL DEFAULT 'Monthly' CHECK (billing_cycle IN ('Monthly','Quarterly','Half-Yearly','Annually','One-time')),
  start_date    DATE  NOT NULL DEFAULT CURRENT_DATE,
  end_date      DATE,
  status        TEXT  NOT NULL DEFAULT 'Active' CHECK (status IN ('Active','Inactive','Completed')),
  notes         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.fee_invoices (
  id           UUID  PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id      UUID  NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id    UUID  NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  engagement_id UUID REFERENCES public.fee_engagements(id),
  invoice_no   TEXT  NOT NULL,
  invoice_date DATE  NOT NULL DEFAULT CURRENT_DATE,
  amount_paise BIGINT NOT NULL DEFAULT 0,
  gst_paise    BIGINT NOT NULL DEFAULT 0,  -- 18% GST — SAC 998211
  total_paise  BIGINT NOT NULL DEFAULT 0,
  status       TEXT  NOT NULL DEFAULT 'Draft' CHECK (status IN ('Draft','Sent','Paid','Overdue')),
  due_date     DATE,
  notes        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.fee_receipts (
  id            UUID  PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id       UUID  NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  invoice_id    UUID  NOT NULL REFERENCES public.fee_invoices(id) ON DELETE CASCADE,
  receipt_date  DATE  NOT NULL DEFAULT CURRENT_DATE,
  amount_paise  BIGINT NOT NULL DEFAULT 0,
  payment_mode  TEXT  NOT NULL DEFAULT 'NEFT' CHECK (payment_mode IN ('NEFT','RTGS','IMPS','UPI','Cheque','Cash')),
  reference_no  TEXT,
  notes         TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.fee_engagements ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fee_invoices    ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.fee_receipts    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "fee_engagements_own_firm" ON public.fee_engagements;
CREATE POLICY "fee_engagements_own_firm" ON public.fee_engagements
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "fee_invoices_own_firm" ON public.fee_invoices;
CREATE POLICY "fee_invoices_own_firm" ON public.fee_invoices
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "fee_receipts_own_firm" ON public.fee_receipts;
CREATE POLICY "fee_receipts_own_firm" ON public.fee_receipts
  FOR ALL USING (
    invoice_id IN (SELECT id FROM public.fee_invoices WHERE firm_id = get_my_firm_id())
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.fee_engagements TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.fee_invoices    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.fee_receipts    TO authenticated;

-- ─── 4. DSC TRACKER ──────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.dsc_records (
  id           UUID  PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id      UUID  NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  holder_name  TEXT  NOT NULL,
  pan          TEXT,
  dsc_type     TEXT  NOT NULL DEFAULT 'Class 3' CHECK (dsc_type IN ('Class 2','Class 3')),
  purpose      TEXT  NOT NULL DEFAULT 'Income Tax',  -- e.g. 'GST', 'MCA', 'Income Tax', 'Tender'
  issued_date  DATE,
  expiry_date  DATE  NOT NULL,
  issued_by    TEXT,  -- CA/TS/NSDL/eMudhra etc.
  token_no     TEXT,
  notes        TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.dsc_records ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "dsc_records_own_firm" ON public.dsc_records;
CREATE POLICY "dsc_records_own_firm" ON public.dsc_records
  FOR ALL USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.dsc_records TO authenticated;

-- ─── 5. TDS DEDUCTIONS ───────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.tds_deductions (
  id              UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id         UUID    NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID    NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  deductee_name   TEXT    NOT NULL,
  deductee_pan    TEXT,
  section         TEXT    NOT NULL,  -- e.g. '194C', '194J', '192'
  transaction_date DATE   NOT NULL,
  payment_amount_paise BIGINT NOT NULL DEFAULT 0,
  tds_rate_pct    NUMERIC(5,2) NOT NULL DEFAULT 0,
  tds_paise       BIGINT  NOT NULL DEFAULT 0,
  challan_no      TEXT,
  challan_date    DATE,
  bsr_code        TEXT,
  status          TEXT    NOT NULL DEFAULT 'deducted' CHECK (status IN ('deducted','deposited','filed')),
  quarter         TEXT,   -- e.g. 'Q1 2026-27'
  return_type     TEXT    NOT NULL DEFAULT '26Q' CHECK (return_type IN ('24Q','26Q','27Q','27EQ')),
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.tds_deductions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tds_deductions_own_firm" ON public.tds_deductions;
CREATE POLICY "tds_deductions_own_firm" ON public.tds_deductions
  FOR ALL USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.tds_deductions TO authenticated;

-- ─── 6. TAX AUDIT CHECKLISTS (Form 3CD) ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.tax_audit_checklists (
  id           UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id      UUID    NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id    UUID    NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year TEXT  NOT NULL DEFAULT '2025-26',
  clauses_json JSONB   NOT NULL DEFAULT '{}',
  status       TEXT    NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','review','finalised')),
  created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (firm_id, client_id, financial_year)
);

ALTER TABLE public.tax_audit_checklists ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tax_audit_own_firm" ON public.tax_audit_checklists;
CREATE POLICY "tax_audit_own_firm" ON public.tax_audit_checklists
  FOR ALL USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.tax_audit_checklists TO authenticated;

-- ─── 7. INCOME TAX NOTICES ───────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.tax_notices (
  id              UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id         UUID    NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID    NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  notice_type     TEXT    NOT NULL,  -- e.g. '143(1)', '148', '139(9)', 'SCN'
  section         TEXT,
  assessment_year TEXT,
  received_date   DATE    NOT NULL,
  response_due    DATE,
  demand_paise    BIGINT  NOT NULL DEFAULT 0,
  status          TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open','response_filed','closed','appeal_filed','awaiting_hearing')),
  priority        TEXT    NOT NULL DEFAULT 'medium' CHECK (priority IN ('critical','high','medium','low')),
  description     TEXT,
  response_notes  TEXT,
  closed_date     DATE,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.tax_notices ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tax_notices_own_firm" ON public.tax_notices;
CREATE POLICY "tax_notices_own_firm" ON public.tax_notices
  FOR ALL USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.tax_notices TO authenticated;

-- ─── 8. CLIENT DOCUMENTS VAULT ───────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.client_documents (
  id            UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id       UUID    NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id     UUID    NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  file_name     TEXT    NOT NULL,
  file_path     TEXT    NOT NULL,  -- Supabase Storage path
  file_size     BIGINT  NOT NULL DEFAULT 0,  -- bytes
  mime_type     TEXT,
  doc_type      TEXT    NOT NULL DEFAULT 'Other',  -- e.g. 'PAN', 'GSTIN', 'Bank Statement', 'ITR', 'Form 16'
  financial_year TEXT,
  description   TEXT,
  tags          TEXT[],
  expiry_date   DATE,
  uploaded_by   UUID    REFERENCES public.users(id),
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.client_documents ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "client_documents_own_firm" ON public.client_documents;
CREATE POLICY "client_documents_own_firm" ON public.client_documents
  FOR ALL USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_documents TO authenticated;

-- ─── 9. BANK RECONCILIATION MATCHES ──────────────────────────────────────────
-- (bank_transactions already exists from migration 006)

CREATE TABLE IF NOT EXISTS public.bank_reconciliation_matches (
  id                  UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id             UUID    NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  bank_transaction_id UUID    NOT NULL REFERENCES public.bank_transactions(id) ON DELETE CASCADE,
  journal_line_id     UUID    REFERENCES public.journal_lines(id),
  match_type          TEXT    NOT NULL DEFAULT 'manual' CHECK (match_type IN ('auto','manual')),
  match_score         NUMERIC(5,2),
  matched_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  matched_by          UUID    REFERENCES public.users(id),
  notes               TEXT
);

ALTER TABLE public.bank_reconciliation_matches ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "bank_recon_own_firm" ON public.bank_reconciliation_matches;
CREATE POLICY "bank_recon_own_firm" ON public.bank_reconciliation_matches
  FOR ALL USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.bank_reconciliation_matches TO authenticated;

-- ─── 10. SALES INVOICES (GST-compliant) ──────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.sales_invoices (
  id              UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id         UUID    NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID    NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  invoice_no      TEXT    NOT NULL,
  invoice_date    DATE    NOT NULL DEFAULT CURRENT_DATE,
  invoice_type    TEXT    NOT NULL DEFAULT 'Tax Invoice' CHECK (invoice_type IN ('Tax Invoice','Bill of Supply','Credit Note','Debit Note')),
  place_of_supply TEXT,
  is_igst         BOOLEAN NOT NULL DEFAULT false,
  subtotal_paise  BIGINT  NOT NULL DEFAULT 0,
  cgst_paise      BIGINT  NOT NULL DEFAULT 0,
  sgst_paise      BIGINT  NOT NULL DEFAULT 0,
  igst_paise      BIGINT  NOT NULL DEFAULT 0,
  total_paise     BIGINT  NOT NULL DEFAULT 0,
  status          TEXT    NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','sent','paid','cancelled')),
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.invoice_lines (
  id              UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  invoice_id      UUID    NOT NULL REFERENCES public.sales_invoices(id) ON DELETE CASCADE,
  description     TEXT    NOT NULL,
  sac_code        TEXT    NOT NULL DEFAULT '998211',
  quantity        NUMERIC(10,2) NOT NULL DEFAULT 1,
  rate_paise      BIGINT  NOT NULL DEFAULT 0,
  amount_paise    BIGINT  NOT NULL DEFAULT 0,
  gst_rate_pct    NUMERIC(5,2) NOT NULL DEFAULT 18,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.sales_invoices ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.invoice_lines  ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "sales_invoices_own_firm" ON public.sales_invoices;
CREATE POLICY "sales_invoices_own_firm" ON public.sales_invoices
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "invoice_lines_own_firm" ON public.invoice_lines;
CREATE POLICY "invoice_lines_own_firm" ON public.invoice_lines
  FOR ALL USING (
    invoice_id IN (SELECT id FROM public.sales_invoices WHERE firm_id = get_my_firm_id())
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.sales_invoices TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.invoice_lines  TO authenticated;

-- ─── 11. TAX PLANNING (Income Tax deductions planner) ────────────────────────

CREATE TABLE IF NOT EXISTS public.tax_planning_records (
  id              UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id         UUID    NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID    NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year  TEXT    NOT NULL DEFAULT '2025-26',
  gross_income_paise BIGINT NOT NULL DEFAULT 0,
  -- 80C investments
  ppf_paise       BIGINT NOT NULL DEFAULT 0,
  elss_paise      BIGINT NOT NULL DEFAULT 0,
  lic_paise       BIGINT NOT NULL DEFAULT 0,
  nsc_paise       BIGINT NOT NULL DEFAULT 0,
  home_loan_principal_paise BIGINT NOT NULL DEFAULT 0,
  tuition_fees_paise BIGINT NOT NULL DEFAULT 0,
  other_80c_paise BIGINT NOT NULL DEFAULT 0,
  -- Other deductions
  hra_paise       BIGINT NOT NULL DEFAULT 0,
  nps_80ccd_paise BIGINT NOT NULL DEFAULT 0,
  health_insurance_80d_paise BIGINT NOT NULL DEFAULT 0,
  home_loan_interest_24b_paise BIGINT NOT NULL DEFAULT 0,
  other_deductions_paise BIGINT NOT NULL DEFAULT 0,
  -- Computed
  regime          TEXT NOT NULL DEFAULT 'new' CHECK (regime IN ('old','new')),
  tax_paise       BIGINT NOT NULL DEFAULT 0,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (firm_id, client_id, financial_year)
);

ALTER TABLE public.tax_planning_records ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "tax_planning_own_firm" ON public.tax_planning_records;
CREATE POLICY "tax_planning_own_firm" ON public.tax_planning_records
  FOR ALL USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.tax_planning_records TO authenticated;

-- ─── 12. MSME TRACKER ────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.msme_vendors (
  id              UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id         UUID    NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID    NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  vendor_name     TEXT    NOT NULL,
  vendor_pan      TEXT,
  msme_reg_no     TEXT,
  msme_category   TEXT    NOT NULL DEFAULT 'Micro' CHECK (msme_category IN ('Micro','Small','Medium')),
  outstanding_paise BIGINT NOT NULL DEFAULT 0,
  invoice_date    DATE,
  due_date        DATE,  -- 45 days from invoice for MSME (Section 43B(h) IT Act)
  payment_date    DATE,
  status          TEXT    NOT NULL DEFAULT 'outstanding' CHECK (status IN ('outstanding','paid','overdue')),
  financial_year  TEXT    NOT NULL DEFAULT '2025-26',
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.msme_vendors ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "msme_vendors_own_firm" ON public.msme_vendors;
CREATE POLICY "msme_vendors_own_firm" ON public.msme_vendors
  FOR ALL USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON public.msme_vendors TO authenticated;

-- ─── 13. RETAINER TRACKER ────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.retainer_clients (
  id              UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  firm_id         UUID    NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID    NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  monthly_fee_paise BIGINT NOT NULL DEFAULT 0,
  services        TEXT[],
  start_date      DATE    NOT NULL DEFAULT CURRENT_DATE,
  end_date        DATE,
  is_active       BOOLEAN NOT NULL DEFAULT true,
  notes           TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS public.retainer_logs (
  id              UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
  retainer_id     UUID    NOT NULL REFERENCES public.retainer_clients(id) ON DELETE CASCADE,
  month           TEXT    NOT NULL,  -- e.g. '2026-06'
  work_done       TEXT,
  hours           NUMERIC(6,2) NOT NULL DEFAULT 0,
  invoice_raised  BOOLEAN NOT NULL DEFAULT false,
  invoice_id      UUID    REFERENCES public.fee_invoices(id),
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.retainer_clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.retainer_logs    ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "retainer_clients_own_firm" ON public.retainer_clients;
CREATE POLICY "retainer_clients_own_firm" ON public.retainer_clients
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "retainer_logs_own_firm" ON public.retainer_logs;
CREATE POLICY "retainer_logs_own_firm" ON public.retainer_logs
  FOR ALL USING (
    retainer_id IN (SELECT id FROM public.retainer_clients WHERE firm_id = get_my_firm_id())
  );

GRANT SELECT, INSERT, UPDATE, DELETE ON public.retainer_clients TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.retainer_logs    TO authenticated;

-- ─── 14. FIRMS TABLE — add missing columns ───────────────────────────────────

ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS gstin     TEXT;
ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS pan       TEXT;
ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS icai_mrn  TEXT;
ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS phone     TEXT;
ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS email     TEXT;
ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS address   TEXT;
ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS city      TEXT;
ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS state     TEXT;
ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS pincode   TEXT;
ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS logo_url  TEXT;
ALTER TABLE public.firms ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- ─── 15. CLIENTS TABLE — add mobile column alias ─────────────────────────────
-- Some pages use client.phone, actual column is mobile
ALTER TABLE public.clients ADD COLUMN IF NOT EXISTS phone TEXT
  GENERATED ALWAYS AS (mobile) STORED;

-- ─── 16. Grant sequences ──────────────────────────────────────────────────────
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO authenticated;

-- ─── 17. Supabase Storage bucket for documents ───────────────────────────────
-- Run this separately in Storage tab if bucket doesn't exist:
-- INSERT INTO storage.buckets (id, name, public) VALUES ('documents', 'documents', false)
-- ON CONFLICT DO NOTHING;

-- ─── DONE ─────────────────────────────────────────────────────────────────────
-- All tables created. No data was modified. Safe to re-run.
-- After running, refresh your app — all pages should work without DB errors.
