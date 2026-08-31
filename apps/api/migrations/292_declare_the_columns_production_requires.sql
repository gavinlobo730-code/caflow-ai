-- ============================================================================
-- 292 — declare the columns production already requires
--
-- WHAT WAS WRONG
--     35 columns are NOT NULL with no default in the live database and merely
--     nullable in the migrations. Nothing compared the two, so the declaration
--     and the reality drifted apart silently.
--
--     That gap is not theoretical. An audit read migration 052, concluded
--     form_26as_uploads.uploaded_by did not exist, and deleted the code that
--     wrote it. The column exists in production, is NOT NULL and has no
--     default, so every 26AS upload failed there — silently, while the whole
--     test suite passed. The audit was careful; it read the wrong source, and
--     nothing could tell it so. scripts/db/schema_drift.py now can, and these
--     35 columns are the first thing it found.
--
-- NOTHING IS BROKEN TODAY, AND THAT IS NOT THE POINT
--     All 19 insert sites that touch these tables already write every column
--     production requires — checked one at a time, including the two that
--     spread a caller's dict, where the Pydantic model makes the fields
--     mandatory. No insert is currently failing.
--
--     But a reader of the migrations sees "nullable", writes code that omits
--     the column, and that code passes every check here and fails there. That
--     is exactly how uploaded_by was lost. Declaring the truth is what stops
--     the next one.
--
-- WHAT THIS DOES, AND WHAT IT COSTS
--     SET NOT NULL on each column. In PRODUCTION every one is already NOT
--     NULL, so this is a no-op there — it changes the declaration, not the
--     database. The CI template is schema-only and holds no rows, so it cannot
--     fail on existing data either.
--
--     Each statement is guarded on the column existing AND being nullable, so
--     re-running is a no-op and an environment where a prior migration never
--     applied is skipped rather than broken. Ten migrations sit on
--     test_migrations_apply's EXPECTED_MIGRATION_FAILURES and do not apply
--     locally, which is precisely why an unguarded ALTER would break the
--     template build.
--
-- NO DATA IS TOUCHED. No column is added, dropped or retyped. A row violating
-- one of these constraints cannot exist in production, because the constraint
-- is already there.
-- ============================================================================

DO $do$
DECLARE
  target RECORD;
BEGIN
  FOR target IN
    SELECT * FROM (VALUES
      ('audit_log', 'entity_id'),
      ('brought_forward_losses', 'created_by'),
      ('brought_forward_losses', 'expiry_assessment_year'),
      ('einvoice_records', 'created_by'),
      ('einvoice_records', 'invoice_date'),
      ('eway_bill_records', 'created_by'),
      ('financial_statement_versions', 'client_id'),
      ('financial_statement_versions', 'financial_year'),
      ('form_26as_reconciliations', 'created_by'),
      ('form_26as_reconciliations', 'financial_year'),
      ('form_26as_reconciliations', 'upload_id'),
      ('form_26as_records', 'financial_year'),
      ('form_26as_records', 'part'),
      ('form_26as_records', 'record_type'),
      ('form_26as_uploads', 'uploaded_by'),
      ('gst_sync_jobs', 'triggered_by'),
      ('itr_filing_versions', 'created_by'),
      ('itr_filings', 'created_by'),
      ('tally_migration_items', 'item_type'),
      ('tally_migration_jobs', 'created_by'),
      ('tally_migration_jobs', 'name'),
      ('tally_migration_jobs', 'source_file_name'),
      ('tally_migration_jobs', 'target_financial_year'),
      ('tax_computation_snapshots', 'assessment_year'),
      ('tax_computation_snapshots', 'created_by'),
      ('tax_computation_snapshots', 'regime'),
      ('tax_deduction_claims', 'created_by'),
      ('tax_disallowances', 'created_by'),
      ('tax_disallowances', 'description'),
      ('workflow_steps', 'name'),
      ('workflow_steps', 'step_type'),
      ('workflow_steps', 'template_id'),
      ('xbrl_packages', 'created_by'),
      ('year_end_exports', 'client_id'),
      ('year_end_exports', 'financial_year')
    ) AS t(tbl, col)
  LOOP
    IF EXISTS (
      SELECT 1 FROM information_schema.columns
      WHERE table_schema = 'public'
        AND table_name  = target.tbl
        AND column_name = target.col
        AND is_nullable = 'YES'
    ) THEN
      EXECUTE format('ALTER TABLE public.%I ALTER COLUMN %I SET NOT NULL',
                     target.tbl, target.col);
      RAISE NOTICE 'set NOT NULL: %.%', target.tbl, target.col;
    END IF;
  END LOOP;
END
$do$;
