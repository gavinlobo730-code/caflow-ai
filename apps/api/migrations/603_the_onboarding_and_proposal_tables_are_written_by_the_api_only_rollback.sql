-- Rollback of migration 603: gives `authenticated` back the write verbs production held on the five onboarding and proposal tables on
-- 15-11-2026 (INSERT, UPDATE and DELETE; the row policies still decide which rows). TRUNCATE is not given back: a platform default PostgREST
-- does not expose. The API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['onboarding_checklists', 'onboarding_checklist_steps', 'onboarding_tasks', 'proposals', 'engagement_events'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
