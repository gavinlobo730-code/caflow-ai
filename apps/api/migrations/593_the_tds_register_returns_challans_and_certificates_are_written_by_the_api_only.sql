-- Migration 593: the TDS register, the TDS returns, the TDS challans and the TDS certificates are written by the API only (ledger POST-A-443).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Migration 345 left the signed-in role INSERT and UPDATE (Executive and above) and DELETE (Manager and above) on `tds_deductions`,
-- `tds_returns`, `tds_challans` and `tds_certificates`, behind row policies that ask the firm, the client assignment, the role tier and, from
-- migration 074, that the firm's own practice is a Partner's, and nothing else. Production granted `authenticated` INSERT, UPDATE, DELETE and
-- TRUNCATE on all four, and `anon` TRUNCATE (read on 15-11-2026; no column-level grant). The browser writes none of the four (it reads
-- `tds_returns`), so a hand-made PostgREST request from a signed-in session was the only way to use the grant, and it recorded a deduction whose
-- tax the engine never computed, a return marked filed with no stated date, or a challan with no duplicate check.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (part 1: `routers/tds_workspace.py`, `services/tds_register_service.py`; the two
-- challan services already wrote with it), and `tests/test_the_tds_register_returns_challans_and_certificates_are_written_with_the_privileged_
-- client.py` holds that over the source. This migration then REVOKES INSERT, UPDATE, DELETE and TRUNCATE on the four tables from
-- `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column level, through PUBLIC) and that `service_role` kept
-- its writes. Reading and the row policies are untouched, so a member still reads the rows of the clients they are assigned to.
--
-- DEPLOY ORDER: part 1 reached production first and this ships at least an hour after it, because an API instance still serving when the grant
-- goes, writing with the caller's own sign-in, would answer "permission denied" to a CA recording a deduction.
--
-- Idempotent. Reversible: 593_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['tds_deductions', 'tds_returns', 'tds_challans', 'tds_certificates'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 593: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 593: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 593: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
