-- Rollback of migration 516: puts back the default migration 069 declared on `model_used`, which names a model Groq retired for
-- this account on 29-09-2026. It is the value 516 removes because it is wrong: after this, a row written by anything that does not
-- set the label is recorded as answered by a model that never saw it. For fidelity with the previous schema, not for use.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['ai_messages', 'ai_summaries', 'ai_recommendations'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL
           AND EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = t AND column_name = 'model_used') THEN
            EXECUTE format('ALTER TABLE public.%I ALTER COLUMN model_used SET DEFAULT %L', t, 'llama-3.3-70b-versatile');
        END IF;
    END LOOP;
END $$;
