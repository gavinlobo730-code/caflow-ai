-- Rollback of migration 705: gives `authenticated` back INSERT, UPDATE and DELETE on `compliance_records` (migrations 010, 041 and 095
-- granted them; migration 489's policies still decide which rows). TRUNCATE is not given back: a platform default PostgREST does not
-- expose. The API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['compliance_records'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
