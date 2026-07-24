-- Migration 234: GST/TDS schema-drift fixes (task #226 audit finding)
--
-- gst_workspace.py's save_gstr1/save_gstr3b/save_gstr9 have always inserted
-- total_*_paise / tax_liability_paise / itc_claimed_paise / net_tax_paise
-- columns that migration 036 never created on gstr1_returns/gstr3b_returns —
-- every "save draft" call for GSTR-1, GSTR-3B, and GSTR-9 has been failing
-- against real Postgres (masked behind a generic "Unable to complete GST
-- operation" try/except). These figures are genuinely needed: the frontend
-- (compliance/gst/page.tsx) reads them back as top-level row fields in the
-- returns list, so they belong on the table, not folded into summary_json.
--
-- domain/income_tax/form26as_service.py's create_upload/save_parsed_records
-- (the upload -> parse -> reconcile pipeline behind /api/form-26as/*, used by
-- clients/[id]/tax/26as/page.tsx) write parse_status/total_records/parsed_at/
-- document_id onto form_26as_uploads — none of which migration 052 created
-- either (that table was shaped for the simpler paste-and-reconcile tool in
-- tds_workspace.py). Every upload/parse call has been failing the same way.

-- ─── gstr1_returns (also stores GSTR-9 rows, return_type='gstr9') ────────────
-- financial_year/return_type are ALSO added by migration 053, but 053 as a
-- whole fails to apply in a fresh run (an unrelated, already-documented R2.6
-- drift-backlog bug — ON_ERROR_STOP aborts the file before reaching these
-- lines; see test_migrations_apply.py's EXPECTED_MIGRATION_FAILURES). Adding
-- them here too, idempotently, makes save_gstr9's F4 tenant-scoping filter
-- (financial_year + return_type) and save_gstr1 actually work regardless of
-- whether 053 is ever fixed.
ALTER TABLE public.gstr1_returns
  ADD COLUMN IF NOT EXISTS total_taxable_paise BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_igst_paise    BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_cgst_paise    BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_sgst_paise    BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_cess_paise    BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_tax_paise     BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS return_type         TEXT NOT NULL DEFAULT 'gstr1',
  ADD COLUMN IF NOT EXISTS financial_year      TEXT;

-- ─── gstr3b_returns ───────────────────────────────────────────────────────────
-- gstin and summary_json were never added by any migration (036's CREATE
-- TABLE omitted both — it only has payload_json, unlike gstr1_returns which
-- has both payload_json AND summary_json) even though save_gstr3b has always
-- inserted them.
ALTER TABLE public.gstr3b_returns
  ADD COLUMN IF NOT EXISTS tax_liability_paise BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS itc_claimed_paise   BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS net_tax_paise       BIGINT NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS gstin               TEXT,
  ADD COLUMN IF NOT EXISTS summary_json        JSONB;

-- ─── form_26as_uploads — the upload->parse->reconcile pipeline's own fields ──
-- (uploaded_by maps onto the table's existing `created_by` column instead of
-- adding a duplicate — no code or frontend reads a separate uploaded_by here.)
ALTER TABLE public.form_26as_uploads
  ADD COLUMN IF NOT EXISTS document_id  UUID,
  ADD COLUMN IF NOT EXISTS parse_status TEXT NOT NULL DEFAULT 'pending'
      CHECK (parse_status IN ('pending','parsed','failed')),
  ADD COLUMN IF NOT EXISTS total_records INTEGER NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS parsed_at    TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS parse_errors JSONB NOT NULL DEFAULT '[]';
