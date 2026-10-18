-- Migration 509: a signed-in session writes none of the workflow tables.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ledger POST-A-248, read from production's grants on 17-10-2026)
-- ═══════════════════════════════════════════════════════════════════════════
-- `authenticated` holds INSERT, UPDATE, DELETE and TRUNCATE on all eleven `workflow_*` tables (`workflows`,
-- `workflow_templates`, `workflow_steps`, `workflow_instances`, `workflow_approvals`, `workflow_executions`,
-- `workflow_failures`, `workflow_schedules`, `workflow_triggers`, `workflow_conditions`, `workflow_action_logs`), and nine of
-- them carry a permissive firm-isolation policy that lets the write through (`workflow_conditions` and `workflow_triggers`
-- have row security on and no policy, so for those two the grant did nothing). No file in `apps/web` reads or writes any of
-- them. So any signed-in member of a firm, whatever the role, could edit a template, change a run, mark an approval decided
-- or forge a failure row directly over PostgREST, without `rbac()`. The approval request's action runs only through the API,
-- so a forged decision runs nothing, but the row and the audit trail lie.
--
-- It is not the payroll shape of migration 499 (the router there already wrote with the privileged client at every site):
-- `repositories/workflow_repository` took `db_provider.request_db`, which on a request under `USE_USER_JWT` (the production
-- default) IS the caller's own session. The scheduler's due-run sweep has no request token and already received the
-- service-role client, so one switch of the repository's WRITE client covers both.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES, AND THE ORDER IT HAS TO BE DEPLOYED IN
-- ═══════════════════════════════════════════════════════════════════════════
-- The repository change ships with this migration: every INSERT, UPDATE and DELETE is made through the privileged client
-- (`_write_db`), names its firm, and addresses a row by firm AND id. The tables that carry no `firm_id` of their own
-- (`workflow_steps`, `workflow_action_logs`) were checked by the caller's row security alone, which the privileged client
-- bypasses, so a write that names a template or a run by its id now asks first that the template or run is the firm's
-- (`_assert_owns`), and `update_schedule_run` takes the firm it was missing. READS stay on the caller's session and row
-- security. This migration then REVOKES INSERT, UPDATE, DELETE and TRUNCATE from `authenticated`, `anon` and PUBLIC on the
-- eleven tables and checks the EFFECTIVE privileges (table, column, and through PUBLIC) before finishing, exactly as 499,
-- 505 and 507 do. Reading, `service_role` and the row policies (kept as the second lock) are untouched. A write from a
-- signed-in session is now "permission denied for table" (SQLSTATE 42501).
--
-- DEPLOY ORDER. Both ship in one merge. The migration job runs as soon as the tests pass while Render rebuilds the API at
-- the same time, so for the minutes in which the OLD API still runs against the revoked grants a workflow write from a
-- request (a template save, an approval decision, a manual run) fails with 42501; the scheduler is unaffected, because it
-- already used the service-role client. The new API works on either side of the migration, because the privileged client
-- never needed the grant.
--
-- Rollback: migration 509_..._rollback.sql grants the privileges back. THAT RE-OPENS THE HOLE; roll the API back first only
-- if the repository must return to the caller's session.

-- Not every table exists on a database built from scratch, and a REVOKE on one that is not there would fail the migration
-- (and with it the required `migration apply` check), so each is asked for first.
DO $$
DECLARE
    tables text[] := ARRAY[
        'workflows', 'workflow_templates', 'workflow_steps', 'workflow_instances', 'workflow_approvals',
        'workflow_executions', 'workflow_failures', 'workflow_schedules', 'workflow_triggers', 'workflow_conditions',
        'workflow_action_logs'
    ];
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        CONTINUE WHEN to_regclass(format('public.%I', t)) IS NULL;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;

    FOREACH t IN ARRAY tables LOOP
        CONTINUE WHEN to_regclass(format('public.%I', t)) IS NULL;
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 509: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 509: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
    END LOOP;
END $$;
