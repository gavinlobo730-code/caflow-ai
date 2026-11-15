-- Rollback of migration 606: gives `authenticated` back the write verbs production held on the four practice work tables on 15-11-2026 (the
-- row policies still decide which rows): INSERT, UPDATE and DELETE on three, and INSERT alone on `knowledge_article_versions`, whose UPDATE and
-- DELETE migration 501 had taken away. TRUNCATE is not given back: a platform default PostgREST does not expose. The API's privileged writes
-- work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['time_entries', 'task_recurring_configs', 'reminders', 'knowledge_article_versions'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        IF t = 'knowledge_article_versions' THEN
            EXECUTE format('GRANT INSERT ON public.%I TO authenticated', t);
        ELSE
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
