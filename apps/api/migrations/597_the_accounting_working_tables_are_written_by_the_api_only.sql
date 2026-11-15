-- Migration 597: the accounting and year-end working tables are written by the API only (ledger POST-A-008, the accounting tranche, part 2
-- of 2).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Nine tables are granted to the signed-in role behind policies that ask the firm (and on five the client assignment) and no role tier:
-- `schedule_iii_ratio_explanations` (the CA's sentence on why a Schedule III ratio moved more than 25%, which clause (Q) requires),
-- `schedule_iii_ratio_inputs` (the principal repaid that Debt Service Coverage needs), `schedule_iii_unbilled_reviews` (the review that lets
-- the unbilled-dues note print a nil), `account_budgets`, `cost_centres`, `year_end_checklist_items`, and `year_end_checklists`,
-- `year_end_reviews` and `notes_to_accounts`, which nothing reads or writes (production has none of the three: the last two are superseded
-- names, core/schema_guard.SUPERSEDED_TABLES, and the first exists only on a database built from the migrations). Production granted
-- `authenticated` INSERT, UPDATE, DELETE and TRUNCATE on the six it has and `anon` TRUNCATE (read on 15-11-2026). The browser writes none of
-- them, so a hand-made PostgREST request from a signed-in session was the only user of the grant, and a Reviewer, who writes nothing through
-- the API, could rewrite the explanation printed on a signed statement or tick a year-end checklist item. Found through POST-A-008's list of
-- the tables a signed-in session reaches outside the access matrix.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (part 1, held over the source by
-- `tests/test_the_accounting_working_tables_are_written_with_the_privileged_client.py`). This migration then REVOKES INSERT, UPDATE, DELETE
-- and TRUNCATE on the nine tables, where they exist, from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level,
-- column level, through PUBLIC) and that `service_role` kept its writes. Reading and the row policies are untouched. The shape is migration
-- 593's.
--
-- DEPLOY ORDER: part 1 reached production first and this ships at least an hour after it, because an API instance still serving when the grant
-- goes, writing with the caller's own sign-in, would answer "permission denied" to a CA recording a budget or ticking a checklist item.
--
-- Idempotent. Reversible: 597_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['schedule_iii_ratio_explanations', 'schedule_iii_ratio_inputs', 'schedule_iii_unbilled_reviews', 'account_budgets', 'cost_centres', 'year_end_checklist_items', 'year_end_checklists', 'year_end_reviews', 'notes_to_accounts'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 597: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 597: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 597: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
