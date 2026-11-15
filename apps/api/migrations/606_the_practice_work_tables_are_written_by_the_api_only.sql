-- Migration 606: the practice's own work tables are written by the API only (ledger POST-A-008, the practice tranche, part 2 of 2).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Four tables are granted to the signed-in role behind policies that ask the firm (and the client assignment where a row names a client) and no
-- role tier: `time_entries` (a member's logged hours, which the unbilled-work list and the practice's profitability read and an invoice marks
-- billed), `task_recurring_configs` (a task the practice repeats on a cadence), `reminders` and `knowledge_article_versions` (each saved
-- version of a knowledge-base article, its history). Production granted `authenticated` INSERT, UPDATE, DELETE and TRUNCATE on the first three
-- and `anon` TRUNCATE, and INSERT alone on `knowledge_article_versions`, whose UPDATE and DELETE migration 501 had already taken away (read on
-- 15-11-2026). The browser writes none of them, and no database function does, so a hand-made PostgREST request from a signed-in session was
-- the only user of the grant, and a signed-in member could rewrite another member's hours, mark logged time billed or add a version to an
-- article's history. Found through POST-A-008's list of the tables a signed-in session reaches outside the access matrix.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (part 1, held over the source by
-- `tests/test_the_practice_work_tables_are_written_with_the_privileged_client.py`), every update and delete naming the firm. This migration then
-- REVOKES INSERT, UPDATE, DELETE and TRUNCATE on the four from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table
-- level, column level, through PUBLIC) and that `service_role` kept its writes. Reading and the row policies are untouched. The shape is
-- migration 593's.
--
-- DEPLOY ORDER: part 1 reached production first and this ships at least an hour after it, because an API instance still serving when the grant
-- goes, writing with the caller's own sign-in, would answer "permission denied" to a CA logging time or saving an article.
--
-- Idempotent. Reversible: 606_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['time_entries', 'task_recurring_configs', 'reminders', 'knowledge_article_versions'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 606: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 606: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 606: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
