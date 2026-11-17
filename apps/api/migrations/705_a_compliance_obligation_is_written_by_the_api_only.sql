-- Migration 705: a compliance obligation is written by the API only (ledger POST-A-461).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- `compliance_records` took a signed-in INSERT, UPDATE and DELETE from any member whose role tier migration 489's policies admit
-- (an assigned Executive among them), and migrations 010, 041 and 095 granted `authenticated` those verbs. The browser only reads the
-- table (`lib/data/compliance.getComplianceCalendarDirect`), so the grant's one use outside the API was a hand-made PostgREST request,
-- and with it an Executive could set an obligation's `status` to 'Not Required' (no reason, no compliance.approve, no audit row, and
-- the obligation left every overdue count) or to 'Filed' (no `filings` row, so no period lock). A trigger keyed on the caller could not
-- tell that write from the API door's while the door wrote as the caller.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (part 1: `repositories/compliance_records_repository.py`, every update naming
-- the firm and the client; `tests/test_a_compliance_obligation_is_written_by_the_api_naming_its_firm_and_client.py`). This migration then
-- REVOKES INSERT, UPDATE, DELETE and TRUNCATE on the table from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege
-- (table level, column level, through PUBLIC) and that `service_role` kept its writes. Reading and the row policies are untouched, so a
-- member still reads the obligations of the clients they are assigned to. No database function writes the table.
--
-- DEPLOY ORDER: part 1 reaches production first and this ships at least an hour after it, because an API instance still serving when the
-- grant goes, writing with the caller's own sign-in, would answer "permission denied" to a CA recording a filing.
--
-- Idempotent. Reversible: 705_..._rollback.sql restores the verbs the earlier migrations granted.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['compliance_records'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 705: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 705: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 705: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
