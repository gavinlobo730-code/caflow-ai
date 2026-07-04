-- ============================================================================
-- 156: Create the F5 backlog — every table/RPC the backend references that no
--      migration ever created (audit F5; roadmap R2.2).
--
-- Scope (verified against the pinned baseline in tests/test_schema_contract.py,
-- which this migration shrinks to empty):
--   Group A — income-tax / GST workspace (13 tables): itr_filings,
--     itr_filing_versions, tax_computation_snapshots, tax_disallowances,
--     tax_deduction_claims, brought_forward_losses, einvoice_records,
--     eway_bill_records, xbrl_packages, gst_sync_jobs, gst_portal_snapshots,
--     form_26as_records, form_26as_reconciliations
--   Group B — Tally migration (2): tally_migration_jobs, tally_migration_items
--   Group C — onboarding / relationships / portal (6): onboarding_checklists,
--     onboarding_checklist_steps, pending_invites,
--     entity_to_entity_relationships, properties, client_portal_sessions
--   RPCs (2): get_cash_payments_above_threshold, increment_message_count
--   (21 tables + 2 functions in total.)
--
-- gst_returns / notices / work_items (the audit's other three phantom names)
-- get NO tables here on purpose: real tables already exist under their true
-- names (gstr1_returns/gstr3b_returns, government_notices, tasks) — the fix
-- for those is in routers/health.py, not new duplicate relations.
--
-- Column sets are derived from the exact payloads the referencing code
-- builds/reads (domain/income_tax/*, domain/gst/portal_service.py,
-- domain/tally/migration_service.py, routers/lifecycle.py,
-- routers/onboarding.py, routers/relationships.py, core/portal_auth.py) and
-- proven by inserting those payloads on a real Postgres 16 before this
-- migration ships. All money columns are BIGINT integer paise (CLAUDE.md).
-- Every table is firm-scoped with the standard RLS predicate.
-- ============================================================================

-- ─── Group A: ITR filing workflow ────────────────────────────────────────────
-- IT Act Section 139 — return filing; internal review workflow before any
-- portal submission. # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT.

CREATE TABLE IF NOT EXISTS public.itr_filings (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year           TEXT NOT NULL,
  assessment_year          TEXT NOT NULL,
  itr_form                 TEXT NOT NULL,           -- ITR-1 … ITR-7
  status                   TEXT NOT NULL DEFAULT 'draft',
  computation_snapshot_id  UUID,
  notes                    TEXT,
  created_by               UUID,
  reviewed_by              UUID,
  reviewed_at              TIMESTAMPTZ,
  partner_reviewed_by      UUID,
  partner_reviewed_at      TIMESTAMPTZ,
  acknowledgement_number   TEXT,
  filing_date              DATE,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_itr_filings_firm_client
  ON public.itr_filings (firm_id, client_id, financial_year);

ALTER TABLE public.itr_filings ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.itr_filings;
CREATE POLICY "firm_isolation" ON public.itr_filings
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.itr_filings TO authenticated, service_role;

-- Immutable JSON versions of a filing (audit trail of every regeneration).
CREATE TABLE IF NOT EXISTS public.itr_filing_versions (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  itr_filing_id  UUID NOT NULL REFERENCES public.itr_filings(id) ON DELETE CASCADE,
  version        INT  NOT NULL,
  json_payload   JSONB NOT NULL DEFAULT '{}',
  created_by     UUID,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_itr_filing_versions_filing
  ON public.itr_filing_versions (itr_filing_id, version);

ALTER TABLE public.itr_filing_versions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.itr_filing_versions;
CREATE POLICY "firm_isolation" ON public.itr_filing_versions
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.itr_filing_versions TO authenticated, service_role;

-- Versioned tax computation snapshots (immutable per version).
-- income_* columns mirror the whitelisted income dict the router accepts
-- (see domain/income_tax/computation_workspace.py::_INCOME_COLUMNS — the
-- insert used to spread arbitrary caller keys as columns; now whitelisted).
CREATE TABLE IF NOT EXISTS public.tax_computation_snapshots (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                   UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id                 UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year            TEXT NOT NULL,
  assessment_year           TEXT,
  version                   INT  NOT NULL DEFAULT 1,
  regime                    TEXT,
  gross_salary_paise        BIGINT NOT NULL DEFAULT 0,
  business_income_paise     BIGINT NOT NULL DEFAULT 0,
  other_income_paise        BIGINT NOT NULL DEFAULT 0,
  total_disallowances_paise BIGINT NOT NULL DEFAULT 0,
  advance_tax_paid_paise    BIGINT NOT NULL DEFAULT 0,
  tds_deducted_paise        BIGINT NOT NULL DEFAULT 0,
  taxable_income_paise      BIGINT NOT NULL DEFAULT 0,
  tax_liability_paise       BIGINT NOT NULL DEFAULT 0,
  net_payable_paise         BIGINT NOT NULL DEFAULT 0,
  is_refund                 BOOLEAN NOT NULL DEFAULT false,
  computation_json          JSONB,
  status                    TEXT NOT NULL DEFAULT 'draft',
  notes                     TEXT,
  created_by                UUID,
  reviewed_by               UUID,
  reviewed_at               TIMESTAMPTZ,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tax_snapshots_firm_client_fy
  ON public.tax_computation_snapshots (firm_id, client_id, financial_year, version DESC);

ALTER TABLE public.tax_computation_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.tax_computation_snapshots;
CREATE POLICY "firm_isolation" ON public.tax_computation_snapshots
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.tax_computation_snapshots TO authenticated, service_role;

-- IT Act Sections 40A(3) / 43B — disallowances workspace.
CREATE TABLE IF NOT EXISTS public.tax_disallowances (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id               UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id             UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year        TEXT NOT NULL,
  section               TEXT NOT NULL,           -- '40A(3)' | '43B_pf' | '43B_gst' | …
  description           TEXT,
  amount_paise          BIGINT NOT NULL DEFAULT 0,
  auto_detected         BOOLEAN NOT NULL DEFAULT false,
  evidence_document_id  UUID,
  journal_entry_id      UUID,
  notes                 TEXT,
  status                TEXT NOT NULL DEFAULT 'pending',  -- pending|accepted|rejected
  created_by            UUID,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tax_disallowances_firm_client_fy
  ON public.tax_disallowances (firm_id, client_id, financial_year);

ALTER TABLE public.tax_disallowances ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.tax_disallowances;
CREATE POLICY "firm_isolation" ON public.tax_disallowances
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.tax_disallowances TO authenticated, service_role;

-- Chapter VI-A deduction claims with evidence.
CREATE TABLE IF NOT EXISTS public.tax_deduction_claims (
  id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id               UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id             UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year        TEXT NOT NULL,
  section               TEXT NOT NULL,           -- '80C' | '80D' | …
  sub_head              TEXT,
  claimed_amount_paise  BIGINT NOT NULL DEFAULT 0,
  allowed_amount_paise  BIGINT NOT NULL DEFAULT 0,
  evidence_document_id  UUID,
  notes                 TEXT,
  status                TEXT NOT NULL DEFAULT 'pending',
  created_by            UUID,
  created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tax_deduction_claims_firm_client_fy
  ON public.tax_deduction_claims (firm_id, client_id, financial_year);

ALTER TABLE public.tax_deduction_claims ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.tax_deduction_claims;
CREATE POLICY "firm_isolation" ON public.tax_deduction_claims
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.tax_deduction_claims TO authenticated, service_role;

-- IT Act Sections 72/74 — brought-forward loss ledger (8-AY carry-forward).
CREATE TABLE IF NOT EXISTS public.brought_forward_losses (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                 UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id               UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  assessment_year         TEXT NOT NULL,
  loss_type               TEXT NOT NULL,          -- business|capital_short|capital_long|house_property
  original_amount_paise   BIGINT NOT NULL DEFAULT 0,
  utilized_amount_paise   BIGINT NOT NULL DEFAULT 0,
  remaining_amount_paise  BIGINT NOT NULL DEFAULT 0,
  expiry_assessment_year  TEXT,
  source_itr_ack          TEXT,
  notes                   TEXT,
  created_by              UUID,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_bf_losses_firm_client
  ON public.brought_forward_losses (firm_id, client_id, assessment_year);

ALTER TABLE public.brought_forward_losses ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.brought_forward_losses;
CREATE POLICY "firm_isolation" ON public.brought_forward_losses
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.brought_forward_losses TO authenticated, service_role;

-- ─── Group A: e-invoice / e-way bill records ─────────────────────────────────
-- CGST Rule 48(4) (e-invoice/IRN) and CGST Rule 138 (e-way bill).
-- # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to IRP/NIC portals.

CREATE TABLE IF NOT EXISTS public.einvoice_records (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id              UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id            UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  sales_invoice_id     UUID,
  invoice_number       TEXT NOT NULL,
  invoice_date         DATE,
  status               TEXT NOT NULL DEFAULT 'draft',   -- draft|generated|cancelled
  provider             TEXT NOT NULL DEFAULT 'manual',
  ca_review_required   BOOLEAN NOT NULL DEFAULT true,
  irn                  TEXT,
  ack_number           TEXT,
  ack_date             TIMESTAMPTZ,
  qr_data              TEXT,
  provider_response    JSONB,
  cancellation_reason  TEXT,
  cancelled_at         TIMESTAMPTZ,
  created_by           UUID,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_einvoice_records_firm_client
  ON public.einvoice_records (firm_id, client_id);

ALTER TABLE public.einvoice_records ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.einvoice_records;
CREATE POLICY "firm_isolation" ON public.einvoice_records
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.einvoice_records TO authenticated, service_role;

CREATE TABLE IF NOT EXISTS public.eway_bill_records (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id              UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id            UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  sales_invoice_id     UUID,
  invoice_number       TEXT NOT NULL,
  vehicle_number       TEXT,
  vehicle_type         TEXT,
  transport_mode       TEXT,
  distance_km          INT,
  transporter_id       TEXT,
  transporter_name     TEXT,
  dispatch_from        TEXT NOT NULL DEFAULT '',
  ship_to              TEXT NOT NULL DEFAULT '',
  goods_description    TEXT NOT NULL DEFAULT '',
  hsn_code             TEXT,
  taxable_value_paise  BIGINT NOT NULL DEFAULT 0,
  status               TEXT NOT NULL DEFAULT 'draft',
  provider             TEXT NOT NULL DEFAULT 'manual',
  ca_review_required   BOOLEAN NOT NULL DEFAULT true,
  ewb_number           TEXT,
  ewb_date             TIMESTAMPTZ,
  ewb_valid_upto       TIMESTAMPTZ,
  provider_response    JSONB,
  extension_reason     TEXT,
  cancellation_reason  TEXT,
  created_by           UUID,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_eway_bill_records_firm_client
  ON public.eway_bill_records (firm_id, client_id);

ALTER TABLE public.eway_bill_records ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.eway_bill_records;
CREATE POLICY "firm_isolation" ON public.eway_bill_records
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.eway_bill_records TO authenticated, service_role;

-- ─── Group A: XBRL packages (Companies Act Section 137, MCA filing prep) ─────

CREATE TABLE IF NOT EXISTS public.xbrl_packages (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year           TEXT NOT NULL,
  taxonomy_version         TEXT NOT NULL DEFAULT 'MCA_2023',
  status                   TEXT NOT NULL DEFAULT 'draft',
  year_end_engagement_id   UUID,
  balance_sheet_json       JSONB,
  pnl_json                 JSONB,
  notes_json               JSONB,
  validation_errors        JSONB,
  missing_tags             JSONB,
  xbrl_xml                 TEXT,
  reviewed_by              UUID,
  reviewed_at              TIMESTAMPTZ,
  created_by               UUID,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_xbrl_packages_firm_client_fy
  ON public.xbrl_packages (firm_id, client_id, financial_year);

ALTER TABLE public.xbrl_packages ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.xbrl_packages;
CREATE POLICY "firm_isolation" ON public.xbrl_packages
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.xbrl_packages TO authenticated, service_role;

-- ─── Group A: GST portal sync (manual/API snapshot store) ────────────────────

CREATE TABLE IF NOT EXISTS public.gst_sync_jobs (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id            UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id          UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  gstin              TEXT NOT NULL,
  sync_type          TEXT NOT NULL DEFAULT 'manual',
  scope              JSONB,
  status             TEXT NOT NULL DEFAULT 'pending',  -- pending|running|completed|failed
  triggered_by       UUID,
  snapshots_created  INT NOT NULL DEFAULT 0,
  started_at         TIMESTAMPTZ,
  completed_at       TIMESTAMPTZ,
  error_message      TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gst_sync_jobs_firm_client
  ON public.gst_sync_jobs (firm_id, client_id);

ALTER TABLE public.gst_sync_jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.gst_sync_jobs;
CREATE POLICY "firm_isolation" ON public.gst_sync_jobs
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gst_sync_jobs TO authenticated, service_role;

CREATE TABLE IF NOT EXISTS public.gst_portal_snapshots (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id       UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  gstin           TEXT NOT NULL,
  snapshot_type   TEXT NOT NULL,          -- 'returns_status' | 'cash_ledger' | …
  data            JSONB,
  sync_job_id     UUID REFERENCES public.gst_sync_jobs(id) ON DELETE SET NULL,
  synced_at       TIMESTAMPTZ,
  financial_year  TEXT,
  period          TEXT,
  provider        TEXT,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_gst_portal_snapshots_firm_client
  ON public.gst_portal_snapshots (firm_id, client_id, snapshot_type);

ALTER TABLE public.gst_portal_snapshots ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.gst_portal_snapshots;
CREATE POLICY "firm_isolation" ON public.gst_portal_snapshots
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.gst_portal_snapshots TO authenticated, service_role;

-- ─── Group A: Form 26AS reconciliation (IT Act Section 203AA) ────────────────
-- Parsed 26AS rows + reconciliation summaries; the upload row itself already
-- exists (form_26as_uploads, migration 072-era) — these are its children.

CREATE TABLE IF NOT EXISTS public.form_26as_records (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                   UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  upload_id                 UUID NOT NULL,
  client_id                 UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  financial_year            TEXT,
  reconciliation_status     TEXT NOT NULL DEFAULT 'unmatched',
  part                      TEXT,
  record_type               TEXT,
  deductor_name             TEXT,
  deductor_tan              TEXT,
  booking_status            TEXT,
  transaction_date          DATE,
  amount_credited_paise     BIGINT NOT NULL DEFAULT 0,
  tds_deposited_paise       BIGINT NOT NULL DEFAULT 0,
  matched_tds_deduction_id  UUID,
  mismatch_reason           TEXT,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_form_26as_records_upload
  ON public.form_26as_records (upload_id);
CREATE INDEX IF NOT EXISTS idx_form_26as_records_firm_client
  ON public.form_26as_records (firm_id, client_id, financial_year);

ALTER TABLE public.form_26as_records ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.form_26as_records;
CREATE POLICY "firm_isolation" ON public.form_26as_records
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.form_26as_records TO authenticated, service_role;

CREATE TABLE IF NOT EXISTS public.form_26as_reconciliations (
  id                         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                    UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id                  UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  upload_id                  UUID,
  financial_year             TEXT,
  total_26as_records         INT NOT NULL DEFAULT 0,
  matched_count              INT NOT NULL DEFAULT 0,
  mismatch_count             INT NOT NULL DEFAULT 0,
  missing_in_books_count     INT NOT NULL DEFAULT 0,
  total_tds_26as_paise       BIGINT NOT NULL DEFAULT 0,
  total_tds_books_paise      BIGINT NOT NULL DEFAULT 0,
  variance_paise             BIGINT NOT NULL DEFAULT 0,
  ai_insight_triggered       BOOLEAN NOT NULL DEFAULT false,
  status                     TEXT NOT NULL DEFAULT 'draft',
  completed_by               UUID,
  completed_at               TIMESTAMPTZ,
  created_by                 UUID,
  created_at                 TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_form_26as_recons_firm_client
  ON public.form_26as_reconciliations (firm_id, client_id, financial_year);

ALTER TABLE public.form_26as_reconciliations ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.form_26as_reconciliations;
CREATE POLICY "firm_isolation" ON public.form_26as_reconciliations
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.form_26as_reconciliations TO authenticated, service_role;

-- ─── Group B: Tally migration engine ─────────────────────────────────────────

CREATE TABLE IF NOT EXISTS public.tally_migration_jobs (
  id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                 UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  -- Target client whose books are being migrated. Nullable: ledger/journal
  -- imports are firm-level, but customer/vendor imports REQUIRE it —
  -- customers.client_id / vendors.client_id are NOT NULL (migration 049), so
  -- the importer refuses those item types on a client-less job (R2.2
  -- adversarial-review finding: they used to fail with an opaque NOT NULL
  -- violation instead).
  client_id               UUID REFERENCES public.clients(id) ON DELETE SET NULL,
  name                    TEXT,
  description             TEXT,
  source_file_name        TEXT,
  source_file_size_bytes  BIGINT,
  import_types            JSONB,
  target_financial_year   TEXT,
  is_dry_run              BOOLEAN NOT NULL DEFAULT false,
  status                  TEXT NOT NULL DEFAULT 'pending',
  total_items             INT NOT NULL DEFAULT 0,
  imported_items          INT NOT NULL DEFAULT 0,
  failed_items            INT NOT NULL DEFAULT 0,
  import_audit_log        JSONB,
  dry_run_report          JSONB,
  completed_at            TIMESTAMPTZ,
  rolled_back_at          TIMESTAMPTZ,
  rolled_back_by          UUID,
  created_by              UUID,
  created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at              TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Self-heal for databases that applied an earlier draft of this migration
-- (CREATE TABLE IF NOT EXISTS silently no-ops, which is exactly the F9
-- partial-application drift mode — same guard pattern as migration 155).
ALTER TABLE public.tally_migration_jobs
  ADD COLUMN IF NOT EXISTS client_id UUID REFERENCES public.clients(id) ON DELETE SET NULL;

CREATE INDEX IF NOT EXISTS idx_tally_migration_jobs_firm
  ON public.tally_migration_jobs (firm_id);

ALTER TABLE public.tally_migration_jobs ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.tally_migration_jobs;
CREATE POLICY "firm_isolation" ON public.tally_migration_jobs
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.tally_migration_jobs TO authenticated, service_role;

CREATE TABLE IF NOT EXISTS public.tally_migration_items (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id              UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  job_id               UUID NOT NULL REFERENCES public.tally_migration_jobs(id) ON DELETE CASCADE,
  item_type            TEXT,               -- 'ledger' | 'voucher' | …
  tally_id             TEXT,
  tally_data           JSONB,
  status               TEXT NOT NULL DEFAULT 'pending',
  validation_errors    JSONB,
  created_record_id    UUID,
  created_record_type  TEXT,               -- table the import created a row in (rollback target)
  error_message        TEXT,
  created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_tally_migration_items_job
  ON public.tally_migration_items (job_id, status);

ALTER TABLE public.tally_migration_items ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.tally_migration_items;
CREATE POLICY "firm_isolation" ON public.tally_migration_items
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.tally_migration_items TO authenticated, service_role;

-- ─── Group C: onboarding checklist (Product Bible Ch. 7) ─────────────────────
-- Code supplies ids explicitly (uuid4 from the router) — defaults still set for
-- any direct SQL use.

CREATE TABLE IF NOT EXISTS public.onboarding_checklists (
  id                        UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                   UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id                 UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  entity_type               TEXT NOT NULL DEFAULT 'Individual',
  status                    TEXT NOT NULL DEFAULT 'in_progress',
  progress_pct              INT NOT NULL DEFAULT 0,
  avg_days_for_entity_type  INT,
  notes                     TEXT,
  started_at                TIMESTAMPTZ,
  completed_at              TIMESTAMPTZ,
  created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_checklists_firm
  ON public.onboarding_checklists (firm_id, status);

ALTER TABLE public.onboarding_checklists ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.onboarding_checklists;
CREATE POLICY "firm_isolation" ON public.onboarding_checklists
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.onboarding_checklists TO authenticated, service_role;

CREATE TABLE IF NOT EXISTS public.onboarding_checklist_steps (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id       UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  workflow_id   UUID NOT NULL REFERENCES public.onboarding_checklists(id) ON DELETE CASCADE,
  step_number   INT NOT NULL,
  title         TEXT NOT NULL DEFAULT '',
  description   TEXT,
  status        TEXT NOT NULL DEFAULT 'pending',  -- pending|done|skipped
  notes         TEXT,
  completed_at  TIMESTAMPTZ,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_onboarding_checklist_steps_workflow
  ON public.onboarding_checklist_steps (workflow_id, step_number);

ALTER TABLE public.onboarding_checklist_steps ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.onboarding_checklist_steps;
CREATE POLICY "firm_isolation" ON public.onboarding_checklist_steps
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.onboarding_checklist_steps TO authenticated, service_role;

-- ─── Group C: pending firm invites ────────────────────────────────────────────
-- Written by routers/onboarding.py's invite email flow. NOTE (flagged in the
-- R2.2 investigation): nothing reads/validates `token` yet — the accept-invite
-- flow validates through migration 153's invite mechanism instead. This table
-- records the outstanding email invites so the write stops 500ing; wiring
-- token validation (or retiring the column) is tracked with the R2.5 follow-ups.

CREATE TABLE IF NOT EXISTS public.pending_invites (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id     UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  email       TEXT NOT NULL,
  role        TEXT NOT NULL,
  token       TEXT NOT NULL UNIQUE,
  invited_by  UUID,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_pending_invites_firm
  ON public.pending_invites (firm_id, email);

ALTER TABLE public.pending_invites ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.pending_invites;
CREATE POLICY "firm_isolation" ON public.pending_invites
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.pending_invites TO authenticated, service_role;

-- ─── Group C: entity relationship intelligence ───────────────────────────────
-- Companies Act Sections 2(87)/2(6); CGST Act Section 2(76) related party.

CREATE TABLE IF NOT EXISTS public.entity_to_entity_relationships (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id            UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  from_entity_id     UUID NOT NULL,
  to_entity_id       UUID NOT NULL,
  relationship_type  TEXT NOT NULL,       -- holding|subsidiary|associate|joint_venture|…
  ownership_percent  NUMERIC(6,3),
  effective_from     DATE,
  effective_to       DATE,
  notes              TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_e2e_relationships_firm
  ON public.entity_to_entity_relationships (firm_id);
CREATE INDEX IF NOT EXISTS idx_e2e_relationships_entities
  ON public.entity_to_entity_relationships (from_entity_id, to_entity_id);

ALTER TABLE public.entity_to_entity_relationships ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.entity_to_entity_relationships;
CREATE POLICY "firm_isolation" ON public.entity_to_entity_relationships
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.entity_to_entity_relationships TO authenticated, service_role;

-- IT Act Sections 22/23/48 — property records with rental income tracking.
CREATE TABLE IF NOT EXISTS public.properties (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id            UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id          UUID REFERENCES public.clients(id) ON DELETE CASCADE,
  entity_id          UUID,
  address            TEXT,
  property_type      TEXT,
  cost_paise         BIGINT NOT NULL DEFAULT 0,
  annual_rent_paise  BIGINT NOT NULL DEFAULT 0,
  acquisition_date   DATE,
  notes              TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_properties_firm_client
  ON public.properties (firm_id, client_id);

ALTER TABLE public.properties ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.properties;
CREATE POLICY "firm_isolation" ON public.properties
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.properties TO authenticated, service_role;

-- ─── Group C: client portal session touches ──────────────────────────────────
-- One row per portal API activity window (written best-effort by
-- core/portal_auth.py — see _touch_portal_session). Read by the health engine
-- as the "client engagement" signal (routers/health.py). Before this
-- migration the table didn't exist AND nothing wrote it — creating it alone
-- would have kept the signal permanently empty, so the writer ships with it.

CREATE TABLE IF NOT EXISTS public.client_portal_sessions (
  id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id            UUID NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  client_id          UUID NOT NULL REFERENCES public.clients(id) ON DELETE CASCADE,
  portal_contact_id  UUID,
  email              TEXT,
  created_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_client_portal_sessions_client
  ON public.client_portal_sessions (firm_id, client_id, created_at DESC);

ALTER TABLE public.client_portal_sessions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firm_isolation" ON public.client_portal_sessions;
CREATE POLICY "firm_isolation" ON public.client_portal_sessions
    USING (firm_id = get_my_firm_id());
GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_portal_sessions TO authenticated, service_role;

-- ─── Missing RPCs ─────────────────────────────────────────────────────────────

-- IT Act Section 40A(3): cash payments above the ₹10,000 threshold, scanned
-- from POSTED journal lines (debit side) against cash-named ledger accounts
-- (chart_of_accounts.account_type is the accounting class — Asset/Liability/…
-- — so "cash" detection is by account name/subtype, the same best-effort the
-- calling code documents). Used by the ITR computation workspace's
-- auto-detect. SECURITY DEFINER so the scan reads journal tables uniformly;
-- firm/client scoping is enforced by the explicit parameter predicates.
-- DROP first: CREATE OR REPLACE cannot change a return type, so shipping a
-- signature fix would otherwise fail on databases that applied an earlier draft.
DROP FUNCTION IF EXISTS public.get_cash_payments_above_threshold(UUID, UUID, BIGINT);
CREATE FUNCTION public.get_cash_payments_above_threshold(
  p_firm_id UUID,
  p_client_id UUID,
  p_threshold_paise BIGINT
) RETURNS TABLE (
  journal_entry_id UUID,
  narration TEXT,
  amount_paise BIGINT,
  entry_date DATE
)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT je.id AS journal_entry_id,
         COALESCE(je.narration, '') AS narration,
         jl.debit_paise AS amount_paise,
         je.entry_date
    FROM public.journal_entries je
    JOIN public.journal_lines jl ON jl.journal_entry_id = je.id
    JOIN public.chart_of_accounts coa ON coa.id = jl.account_id
   WHERE je.firm_id = p_firm_id
     AND je.client_id = p_client_id
     AND je.is_posted = true
     AND je.deleted_at IS NULL
     AND jl.debit_paise > p_threshold_paise
     AND (coa.account_name ILIKE '%cash%' OR coa.account_subtype ILIKE '%cash%')
$$;

GRANT EXECUTE ON FUNCTION public.get_cash_payments_above_threshold(UUID, UUID, BIGINT)
  TO authenticated, service_role;

-- F19 — AI copilot conversation message counter. Parameter is named conv_id
-- because PostgREST RPC dispatch matches by NAME and the caller
-- (repositories/ai_copilot_repository.py) passes {"conv_id": ...}. Returns
-- the NEW count (atomic increment + read in one statement) — callers may
-- ignore it, but must never write it back into message_count themselves.
DROP FUNCTION IF EXISTS public.increment_message_count(UUID);
CREATE FUNCTION public.increment_message_count(
  conv_id UUID
) RETURNS integer
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = public
AS $$
  UPDATE public.ai_conversations
     SET message_count = COALESCE(message_count, 0) + 1,
         last_message_at = now(),
         updated_at = now()
   WHERE id = conv_id
  RETURNING message_count
$$;

GRANT EXECUTE ON FUNCTION public.increment_message_count(UUID)
  TO authenticated, service_role;
