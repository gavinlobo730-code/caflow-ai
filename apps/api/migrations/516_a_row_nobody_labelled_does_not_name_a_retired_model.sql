-- Migration 516: a row nobody labelled does not name a model that has been retired (ledger POST-A-165).
--
-- Migration 069 created `ai_messages`, `ai_summaries` and `ai_recommendations` with `model_used TEXT DEFAULT
-- 'llama-3.3-70b-versatile'`. Groq retired that model for this account on 29-09-2026 (a live `model_not_found` 404), and the code
-- now stamps every row it writes with the model that actually answered (`groq_text.answered_by()`, and the configured model for a
-- recommendation). The column default is what is left: a row written by anything that does NOT set the label, a script, a manual
-- insert, a future writer that forgets, would be recorded as answered by a model that never saw it. Read from production on
-- 18-10-2026: all three columns still carry the retired default, are nullable, and are not constrained.
--
-- WHAT THIS DOES
--   Drops the default on the three columns. NULL is the honest value for "nobody said which model": every reader already treats the
--   label as optional (`MessageOut.model_used` is Optional, the executive dashboard's type is `string | null`, the digest writes None
--   when it did not call a model). No row is changed: rows written while the retired model really did answer carry a label that was
--   true when it was written.
--
-- Idempotent, and metadata only (no table rewrite, no lock beyond a brief catalogue one). Reversible: 516_..._rollback.sql
-- restores the retired default, which is exactly the wrong value this migration removes, so it is for fidelity and not for use.

DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['ai_messages', 'ai_summaries', 'ai_recommendations'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL
           AND EXISTS (SELECT 1 FROM information_schema.columns
                        WHERE table_schema = 'public' AND table_name = t AND column_name = 'model_used') THEN
            EXECUTE format('ALTER TABLE public.%I ALTER COLUMN model_used DROP DEFAULT', t);
        END IF;
    END LOOP;

    -- Closing check: none of the three still carries a default.
    IF EXISTS (SELECT 1
                 FROM pg_attribute a
                 JOIN pg_class c ON c.oid = a.attrelid
                 JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
                WHERE c.relnamespace = 'public'::regnamespace
                  AND c.relname IN ('ai_messages', 'ai_summaries', 'ai_recommendations')
                  AND a.attname = 'model_used' AND NOT a.attisdropped) THEN
        RAISE EXCEPTION 'migration 516: a model_used column still carries a default';
    END IF;
END $$;
