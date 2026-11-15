-- Rollback of migration 601: gives `authenticated` back the write verbs production held on the two delivery record tables on
-- 15-11-2026 (INSERT, UPDATE and DELETE; the row policies still decide which rows). TRUNCATE is not given back: a platform default PostgREST
-- does not expose. The API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['invoice_deliveries', 'customer_statement_deliveries'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
