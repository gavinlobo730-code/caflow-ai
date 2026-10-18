-- Rollback of migration 509: gives `authenticated` back INSERT, UPDATE and DELETE on the workflow tables, as the migrations
-- that created them granted. THIS RE-OPENS THE HOLE: any signed-in member of a firm can again edit a template, change a run,
-- mark an approval decided or forge a failure row directly over PostgREST, without rbac(). The repository writes with the
-- privileged client and works either way, so the API does not have to be rolled back first. TRUNCATE is NOT restored: no
-- migration ever granted it deliberately.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['workflows', 'workflow_templates', 'workflow_steps', 'workflow_instances', 'workflow_approvals',
                             'workflow_executions', 'workflow_failures', 'workflow_schedules', 'workflow_triggers',
                             'workflow_conditions', 'workflow_action_logs'] LOOP
        CONTINUE WHEN to_regclass(format('public.%I', t)) IS NULL;
        EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
    END LOOP;
END $$;
