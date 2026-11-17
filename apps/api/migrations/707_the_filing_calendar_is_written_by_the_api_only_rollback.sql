-- Rollback of migration 707: gives `authenticated` back INSERT, UPDATE and DELETE on `compliance_calendar` (migration 261's policies still
-- decide which rows). TRUNCATE is not given back. The API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['compliance_calendar'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
