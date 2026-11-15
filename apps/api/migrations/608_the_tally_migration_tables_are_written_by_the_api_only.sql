-- Migration 608: the Tally migration tables are written by the API only (ledger POST-A-008, the Tally tranche, part 2 of 2).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Two tables are granted to the signed-in role behind policies that ask the firm (and the client assignment where a job names a client) and no
-- role tier: `tally_migration_jobs` (one upload of a Tally export: its status, its counts, the sentence about its last run) and
-- `tally_migration_items` (each master in it, what it became and why it failed). Production granted `authenticated` INSERT, UPDATE, DELETE and
-- TRUNCATE on both and `anon` TRUNCATE (read on 15-11-2026). The browser writes neither, and no database function does, so a hand-made PostgREST
-- request from a signed-in session was the only user of the grant, and a signed-in member could mark a job imported, point an item at another
-- record (which the job's rollback then deletes) or clear a job's failures. Found through POST-A-008's list of the tables a signed-in session
-- reaches outside the access matrix.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (part 1, held over the source by
-- `tests/test_the_tally_migration_tables_are_written_with_the_privileged_client.py`). This migration then REVOKES INSERT, UPDATE, DELETE and
-- TRUNCATE on the two from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column level, through PUBLIC) and
-- that `service_role` kept its writes. Reading and the row policies are untouched. The shape is migration 593's.
--
-- DEPLOY ORDER: part 1 reached production first and this ships at least an hour after it, because an API instance still serving when the grant
-- goes, writing with the caller's own sign-in, would answer "permission denied" to a CA uploading a Tally export.
--
-- Idempotent. Reversible: 608_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['tally_migration_jobs', 'tally_migration_items'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 608: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 608: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 608: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
