-- Migration 562: seventeen firm-level tables are written by the API only (ledger POST-A-329).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- The writer map of 22-10-2026 found tables the API writes on the CALLER'S OWN session behind a role lower than their data
-- deserves, with no tier at the database, so a member who may only read could write them over PostgREST (read from production on
-- 29-10-2026: `authenticated` held INSERT and UPDATE on all seventeen, and DELETE on sixteen):
--
--   account_group_mappings            a row displaces the CA's own Schedule III mapping and moves a balance on the statements a CA signs
--   firm_hsn_library, firm_hsn_rate_history   firm-wide masters every client's invoices draw on
--   assignment_rules                  redirects who receives other clients' recurring work
--   entities, entity_relationships, entity_to_entity_relationships   the people and companies behind clients (PAN, GSTIN, date of birth)
--   leads, dsc_records                the pipeline and the practice's digital signature tokens
--   automation_rules, automation_executions, reminder_settings   what the practice's automation does and says
--   engagement_templates              the wording of a letter a client signs
--   recurring_invoice_templates, recurring_purchase_bill_templates, recurring_journal_templates   documents that post by themselves
--   task_escalations                  who is told a task is overdue
--
-- The browser never touches any of them (no `.from("<table>")` in `apps/web`), so nothing but the API writes them for a person.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- The API writes all seventeen with the privileged client, after the route's own `rbac()` and ownership checks, naming the firm on
-- every statement (the change that ships with this migration; `tests/test_a_write_of_a_table_the_signed_in_role_cannot_write_is_made_on_a_client_that_can.py`
-- holds it over the whole source). This migration then REVOKES INSERT, UPDATE, DELETE and TRUNCATE on the seventeen from
-- `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column level, through PUBLIC), and that
-- `service_role` kept its writes. Reading, the row policies and every other table are untouched.
--
-- A tier would have been the other answer (a RESTRICTIVE policy asking `my_permission(<resource>, <action>, <floor>)`, as in 487 to
-- 489), and it would have left the people who hold the tier able to rewrite these tables from a hand-made request, skipping the route's
-- own validation. Where the browser does not write a table, taking the write away is the stronger lock and needs no tier to be argued.
--
-- `fx_rates` is NOT in this list: it is global, has its own INSERT and UPDATE policies at `settings:write` (migration 470) and is
-- written by a client of its own (`fx_writer`).
--
-- DEPLOY ORDER: the new API works either side of this migration (a privileged write is a superset of the caller's). For the minutes the
-- OLD API still runs against the revoked grants, saving any of these (a lead, a DSC record, a library code, a template, a rule...)
-- fails with a permission error; nothing is half-written, and the screens say the save failed. The sweeps that write
-- `recurring_*_templates` and `task_escalations` already ran privileged.
--
-- Idempotent. Reversible: 562_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    tables text[] := ARRAY[
        'account_group_mappings', 'firm_hsn_library', 'firm_hsn_rate_history', 'assignment_rules', 'entities',
        'entity_relationships', 'entity_to_entity_relationships', 'leads', 'dsc_records', 'automation_rules',
        'automation_executions', 'reminder_settings', 'engagement_templates', 'recurring_invoice_templates',
        'recurring_purchase_bill_templates', 'recurring_journal_templates', 'task_escalations'
    ];
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;

    FOREACH t IN ARRAY tables LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 562: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 562: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE') THEN
            RAISE EXCEPTION 'migration 562: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
