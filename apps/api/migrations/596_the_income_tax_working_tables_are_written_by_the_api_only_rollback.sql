-- Rollback of migration 596: gives `authenticated` back the write verbs production held on the eleven income-tax working tables on 15-11-2026
-- (INSERT, UPDATE and DELETE; the row policies still decide which rows). TRUNCATE is not given back: a platform default PostgREST does not expose.
-- The API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['ais_uploads', 'ais_records', 'ais_reconciliations', 'ais_computation_decisions', 'form_26as_records', 'income_tax_asset_blocks', 'income_tax_worksheets', 'itr_filing_versions', 'tax_deduction_claims', 'it_deductions', 'tax_notices'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
