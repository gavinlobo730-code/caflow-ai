-- Rollback of migration 599: gives `authenticated` back the write verbs production held on the six client health and lifecycle tables on
-- 15-11-2026 (the row policies still decide which rows): INSERT, UPDATE and DELETE on five, and INSERT and UPDATE on `client_health_scores`,
-- which held no DELETE. TRUNCATE is not given back: a platform default PostgREST does not expose. The API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['client_lifecycle_events', 'client_period_metrics', 'health_overrides', 'client_health_scores', 'health_dimension_scores', 'client_health_overrides'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        IF t = 'client_health_scores' THEN
            EXECUTE format('GRANT INSERT, UPDATE ON public.%I TO authenticated', t);
        ELSE
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
