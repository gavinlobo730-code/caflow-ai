-- Rollback of migration 593: gives `authenticated` back the write verbs production held on the TDS register, the TDS returns, the TDS challans
-- and the TDS certificates on 15-11-2026 (INSERT, UPDATE and DELETE; migration 345's policies still decide which rows). TRUNCATE is not given
-- back: a platform default PostgREST does not expose. The API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['tds_deductions', 'tds_returns', 'tds_challans', 'tds_certificates'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
