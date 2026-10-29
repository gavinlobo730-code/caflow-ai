-- Rollback of migration 562: gives `authenticated` back the write verbs production held on the seventeen tables on 29-10-2026.
-- `firm_hsn_rate_history` never held DELETE for `authenticated` (its delete route was therefore refused in production), so DELETE is
-- not given back there. TRUNCATE is not given back: a platform default PostgREST does not expose. A table that does not exist in
-- this database (production has `assignment_rules`; a database built from the migrations does not) is passed over, as the migration
-- does. The API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'account_group_mappings', 'firm_hsn_library', 'firm_hsn_rate_history', 'assignment_rules', 'entities',
        'entity_relationships', 'entity_to_entity_relationships', 'leads', 'dsc_records', 'automation_rules',
        'automation_executions', 'reminder_settings', 'engagement_templates', 'recurring_invoice_templates',
        'recurring_purchase_bill_templates', 'recurring_journal_templates', 'task_escalations'
    ] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        IF t = 'firm_hsn_rate_history' THEN
            EXECUTE format('GRANT INSERT, UPDATE ON public.%I TO authenticated', t);
        ELSE
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
