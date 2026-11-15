-- Migration 602: five tables nothing writes take no write from a signed-in session (ledger POST-A-008, the unwritten tables).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- `msme_payments`, `msme_vendors`, `retainer_clients`, `suppliers` (the supplier master is `vendors`; this one is retired, see the design
-- record's "THE SUPPLIER MASTER IS `public.vendors`") and `ledger_balances` are written by nothing in the API, the browser or a database
-- function (`ledger_balances` is only read, by the bank account's "is this ledger still used" check). Production granted `authenticated`
-- INSERT, UPDATE, DELETE and TRUNCATE on all five and `anon` TRUNCATE (read on 15-11-2026), so a hand-made PostgREST request from a signed-in
-- session was the only writer any of them could have. Found through POST-A-008's list of the tables a signed-in session reaches outside the
-- access matrix.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- REVOKES INSERT, UPDATE, DELETE and TRUNCATE on the five from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table
-- level, column level, through PUBLIC) and that `service_role` kept its writes. Reading and the row policies are untouched. The shape is
-- migration 593's. There is no part 1: no writer had to move first. Dropping the tables is a separate decision (a drop needs the production
-- schema snapshot refreshed, docs/schema-drift.md) and is not made here.
--
-- Idempotent. Reversible: 602_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['msme_payments', 'msme_vendors', 'retainer_clients', 'suppliers', 'ledger_balances'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 602: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 602: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 602: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
