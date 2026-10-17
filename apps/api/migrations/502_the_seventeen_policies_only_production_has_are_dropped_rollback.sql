-- Rollback of migration 502: recreates the seventeen `firm_iso_*` policies exactly as production's catalogue held them on
-- 17-10-2026 (PERMISSIVE, FOR ALL, PUBLIC, the predicate on the `app.current_firm_id` setting that nothing sets). It
-- RE-ADDS policies no other migration declares; it exists so the drop can be undone.
-- A table that does not exist in the database it is run against is skipped: `workflow_conditions` and `workflow_triggers`
-- exist in production and not in a database built from the migrations.
-- Each policy is dropped first, so running it twice is harmless.
DO $$
DECLARE
  spec record;
BEGIN
  FOR spec IN
    SELECT * FROM (VALUES
      ('ai_actions',          'firm_iso_ai_actions',          'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('ai_context_windows',  'firm_iso_ai_context_windows',  'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('ai_conversations',    'firm_iso_ai_conversations',    'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('ai_feedback',         'firm_iso_ai_feedback',         'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('ai_messages',         'firm_iso_ai_messages',         'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('ai_recommendations',  'firm_iso_ai_recommendations',  'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('ai_summaries',        'firm_iso_ai_summaries',        'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('workflow_approvals',  'firm_iso_wf_approvals',        'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('workflow_executions', 'firm_iso_wf_executions',       'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('workflow_failures',   'firm_iso_wf_failures',         'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('workflow_instances',  'firm_iso_wf_instances',        'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('workflow_schedules',  'firm_iso_wf_schedules',        'firm_id = (current_setting(''app.current_firm_id'', true))::uuid'),
      ('workflow_action_logs', 'firm_iso_wf_action_logs',
       'instance_id IN (SELECT workflow_instances.id FROM workflow_instances WHERE workflow_instances.firm_id = (current_setting(''app.current_firm_id'', true))::uuid)'),
      ('workflow_templates',  'firm_iso_wf_templates',
       'firm_id = (current_setting(''app.current_firm_id'', true))::uuid OR is_system = true'),
      ('workflow_steps',      'firm_iso_wf_steps',
       'template_id IN (SELECT workflow_templates.id FROM workflow_templates WHERE workflow_templates.firm_id = (current_setting(''app.current_firm_id'', true))::uuid OR workflow_templates.is_system = true)'),
      ('workflow_triggers',   'firm_iso_wf_triggers',
       'template_id IN (SELECT workflow_templates.id FROM workflow_templates WHERE workflow_templates.firm_id = (current_setting(''app.current_firm_id'', true))::uuid OR workflow_templates.is_system = true)'),
      ('workflow_conditions', 'firm_iso_wf_conditions',
       'step_id IN (SELECT ws.id FROM workflow_steps ws JOIN workflow_templates wt ON ws.template_id = wt.id WHERE wt.firm_id = (current_setting(''app.current_firm_id'', true))::uuid OR wt.is_system = true)')
    ) AS v(tbl, pol, predicate)
  LOOP
    IF to_regclass('public.' || spec.tbl) IS NOT NULL THEN
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', spec.pol, spec.tbl);
      EXECUTE format('CREATE POLICY %I ON public.%I FOR ALL USING (%s)', spec.pol, spec.tbl, spec.predicate);
    END IF;
  END LOOP;
END $$;
