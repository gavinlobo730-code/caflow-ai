-- Migration 599: the client health and lifecycle tables are written by the API only (ledger POST-A-008, the health tranche, part 2 of 2).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Six tables are granted to the signed-in role behind policies that ask the firm (and the client assignment where a row names a client) and no
-- role tier: `client_lifecycle_events` (the history of a lead and of the client it became), `client_period_metrics` (the year's figures the
-- nightly sweep derives), `health_overrides` (a person's override of a client's health grade, which can mask a real Critical status), and
-- `client_health_scores`, `health_dimension_scores` and `client_health_overrides`, which nothing in the API, the browser or a database function
-- reads or writes (the health engine's scores are `health_scores`). Production granted `authenticated` INSERT and UPDATE on all six, DELETE on
-- five and TRUNCATE on all six, and `anon` TRUNCATE (read on 15-11-2026). The browser writes none of them, so a hand-made PostgREST request
-- from a signed-in session was the only user of the grant, and a Reviewer, who writes nothing through the API, could set an override on a
-- client's grade. Found through POST-A-008's list of the tables a signed-in session reaches outside the access matrix.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (part 1, held over the source by
-- `tests/test_the_health_and_lifecycle_tables_are_written_with_the_privileged_client.py`). This migration then REVOKES INSERT, UPDATE, DELETE
-- and TRUNCATE on the six from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column level, through
-- PUBLIC) and that `service_role` kept its writes. Reading and the row policies are untouched. The shape is migration 593's.
--
-- DEPLOY ORDER: part 1 reached production first and this ships at least an hour after it, because an API instance still serving when the grant
-- goes, writing with the caller's own sign-in, would answer "permission denied" to a CA moving a lead or overriding a grade.
--
-- Idempotent. Reversible: 599_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['client_lifecycle_events', 'client_period_metrics', 'health_overrides', 'client_health_scores', 'health_dimension_scores', 'client_health_overrides'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 599: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 599: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 599: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
