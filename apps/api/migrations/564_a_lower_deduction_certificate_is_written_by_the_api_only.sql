-- Migration 564: a lower-deduction certificate is written by the API only (ledger POST-A-359).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- A certificate under s.197 (Form 13) lowers the rate at which tax is withheld from a real supplier, so a row that should not exist,
-- or one with a rate the supplier's certificate does not carry, under-deducts. The client's Compliance -> TDS tab wrote the table
-- straight from the browser, behind migration 359's role-guarded policies, and production still grants `authenticated` INSERT, UPDATE
-- and DELETE on it, so those policies were the ONLY lock on a hand-made PostgREST call: no route checked the supplier, the section
-- or the dates before the row was stored.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- POST-A-293 moved the only writer onto `POST /api/tds-workspace/lower-deduction-certificates`, which writes with the privileged client
-- after asking the accounting tier, the client, the supplier and the section (`domain/tds/lower_deduction.section_refusal`), and
-- `tests/test_a_section_197_certificate_is_recorded_by_the_server.py` holds that over the source. This migration then REVOKES INSERT,
-- UPDATE, DELETE and TRUNCATE on the table from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level,
-- column level, through PUBLIC) and that `service_role` kept its writes. Reading and the row policies are untouched.
--
-- DEPLOY ORDER: the API change reached production first and this ships at least an hour after it, because the OLD browser bundle
-- against revoked grants fails soft and wrong. No endpoint deletes a certificate (the policy said Manager and above), so ending a
-- certificate's validity is still not possible from the product.
--
-- Idempotent. Reversible: 564_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text := 'tds_lower_deduction_certificates';
    r text;
    verb text;
BEGIN
    IF to_regclass(format('public.%I', t)) IS NULL THEN
        RETURN;
    END IF;
    EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
            IF has_table_privilege(r, format('public.%I', t), verb) THEN
                RAISE EXCEPTION 'migration 564: % still holds % on %', r, verb, t;
            END IF;
        END LOOP;
        IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
           OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
            RAISE EXCEPTION 'migration 564: % still holds a column-level write privilege on %', r, t;
        END IF;
    END LOOP;
    IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
       OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE') THEN
        RAISE EXCEPTION 'migration 564: service_role lost its write on %', t;
    END IF;
END $$;
