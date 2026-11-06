-- Migration 583: the e-invoice records, the e-way bill records and the section 140A challans are written by the API only (ledger POST-A-394).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Production grants `authenticated` INSERT, UPDATE, DELETE and TRUNCATE on `einvoice_records`, `eway_bill_records` and
-- `self_assessment_challans` (read from the database on 6-11-2026; `anon` held TRUNCATE), behind row policies that ask the firm and the
-- client assignment and nothing else. So a hand-made PostgREST request from a signed-in session could write an IRN record, an e-way bill
-- record or a Challan 280 that no route would have written: the routes ask the day a portal printed, whose invoice a record names and
-- whether the challan is a duplicate, and the table asks none of them. The browser never reaches the three tables (a test holds that).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (`domain/income_tax/einvoice_service.py`, `eway_service.py`; the challans'
-- router already wrote with `service_db_or_none`), and `tests/test_the_irn_ewb_and_self_assessment_challan_writes_use_the_privileged_
-- client.py` holds that over the source. This migration then REVOKES INSERT, UPDATE, DELETE and TRUNCATE on the three tables from
-- `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column level, through PUBLIC) and that
-- `service_role` kept its writes. Reading and the row policies are untouched.
--
-- DEPLOY ORDER: the API change reached production first and this ships at least an hour after it, because an API instance still serving
-- when the grant goes, writing with the caller's own sign-in, would answer "permission denied" to a CA recording an IRN.
--
-- Idempotent. Reversible: 583_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['einvoice_records', 'eway_bill_records', 'self_assessment_challans'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 583: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 583: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 583: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
