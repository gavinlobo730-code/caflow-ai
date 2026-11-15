-- Migration 605: the online-payment tables are written by the API only (ledger POST-A-008, the payments tranche, part 2 of 2).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Three tables are granted to the signed-in role behind policies that ask the firm (and the client assignment where a row names a client) and no
-- role tier: `customer_payment_links` (a hosted payment link for an invoice's outstanding balance), `customer_payments` (what a gateway
-- reported paid, and the receipt it settled into) and `customer_payment_events` (each webhook delivery, the replay guard). Production granted
-- `authenticated` INSERT, UPDATE, DELETE and TRUNCATE on all three and `anon` TRUNCATE (read on 15-11-2026). The browser writes none of them,
-- and no database function does, so a hand-made PostgREST request from a signed-in session was the only user of the grant, and a signed-in
-- member could mark a payment captured, point it at another receipt or forge a delivery row. Found through POST-A-008's list of the tables a
-- signed-in session reaches outside the access matrix.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (part 1, held over the source by
-- `tests/test_the_online_payment_tables_are_written_with_the_privileged_client.py`): staff making a link and a portal client paying wrote with
-- their own sign-in until then, and the gateway's webhook writes with the service client as it always did. This migration then REVOKES INSERT,
-- UPDATE, DELETE and TRUNCATE on the three from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column
-- level, through PUBLIC) and that `service_role` kept its writes. Reading and the row policies are untouched. The shape is migration 593's.
--
-- DEPLOY ORDER: part 1 reached production first and this ships at least an hour after it, because an API instance still serving when the grant
-- goes, writing with the caller's own sign-in, would answer "permission denied" to a CA making a payment link.
--
-- Idempotent. Reversible: 605_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['customer_payment_links', 'customer_payments', 'customer_payment_events'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 605: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 605: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 605: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
