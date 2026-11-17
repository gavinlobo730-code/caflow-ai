-- Migration 707: the filing calendar is written by the API only (ledger POST-A-208, part 5).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- `compliance_calendar` granted the signed-in role INSERT, UPDATE and DELETE behind migration 261's tier policies. Since part 4 of
-- POST-A-208 no screen reads or writes it (the firm-level GST and income-tax trackers ask `GET /api/compliance/calendar/tracker` and
-- `POST /api/compliance/calendar`), so the grant's one use outside the API was a hand-made PostgREST request, and with it a member could
-- tick a return filed without the `filings` row that locks its period, or delete a deadline, with no audit event.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's two writers (`routers/compliance.py`: the add and Mark Filed) write with the privileged client since the change that
-- shipped before this one, naming the firm and the client (`tests/test_the_filing_calendar_is_written_by_the_api_naming_its_firm_and_
-- client.py`). This migration REVOKES INSERT, UPDATE, DELETE and TRUNCATE on the table from `authenticated`, `anon` and PUBLIC and checks
-- the EFFECTIVE privilege and that `service_role` kept its writes. Reading and the row policies are untouched. No database function or
-- rule writes the table: migration 012's `compliance_entries` view over it, with its insert rule, was replaced by migration 016 with a
-- view over `compliance_tasks`, and migration 582 dropped that.
--
-- DEPLOY ORDER: the code reaches production first and this ships at least an hour after it.
--
-- Idempotent. Reversible: 707_..._rollback.sql restores the three verbs.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['compliance_calendar'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 707: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 707: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 707: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
