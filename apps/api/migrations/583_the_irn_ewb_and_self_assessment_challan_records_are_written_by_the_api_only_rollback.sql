-- Rollback of migration 583: gives `authenticated` back the write verbs production held on the e-invoice records, the e-way bill records and
-- the section 140A challans on 6-11-2026 (INSERT, UPDATE and DELETE). TRUNCATE is not given back: a platform default PostgREST does not expose.
-- The API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['einvoice_records', 'eway_bill_records', 'self_assessment_challans'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
