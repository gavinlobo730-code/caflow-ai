-- Migration 600: the recurring and billing tables are written by the API only (ledger POST-A-008, the recurring-billing tranche, part 2 of 2).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Six tables are granted to the signed-in role behind policies that ask the firm (and on a schedule the client assignment) and no role tier:
-- `billing_schedules` (the practice's retainers, which generate its own fee invoices), `recurring_invoice_template_lines` and
-- `recurring_purchase_bill_template_lines` (what a template will next raise as an invoice or a bill), and the run logs `recurring_invoice_runs`,
-- `recurring_purchase_bill_runs` and `recurring_journal_runs` (a run logged as done is skipped by the sweep). Production granted `authenticated`
-- INSERT, UPDATE, DELETE and TRUNCATE on all six and `anon` TRUNCATE (read on 15-11-2026). The browser writes none of them, and no database
-- function does, so a hand-made PostgREST request from a signed-in session was the only user of the grant. Found through POST-A-008's list of
-- the tables a signed-in session reaches outside the access matrix.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (part 1, held over the source by
-- `tests/test_the_recurring_billing_tables_are_written_with_the_privileged_client.py`). This migration then REVOKES INSERT, UPDATE, DELETE and
-- TRUNCATE on the six from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column level, through PUBLIC)
-- and that `service_role` kept its writes. Reading and the row policies are untouched. The shape is migration 593's.
--
-- DEPLOY ORDER: part 1 reached production first and this ships at least an hour after it, because an API instance still serving when the grant
-- goes, writing with the caller's own sign-in, would answer "permission denied" to a CA editing a template or a retainer.
--
-- Idempotent. Reversible: 600_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['billing_schedules', 'recurring_invoice_template_lines', 'recurring_purchase_bill_template_lines', 'recurring_invoice_runs', 'recurring_purchase_bill_runs', 'recurring_journal_runs'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 600: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 600: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 600: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
