-- Rollback of migration 503: puts back the two policies exactly as migration 157 declared them and production holds them
-- (read on 17-10-2026). THIS RE-OPENS THE HOLE the migration closes: any signed-in member of any firm can then write a
-- system workflow template, or an own-firm one marked as a system template, that every firm reads. It is here so the change
-- is a decision that can be undone. Running it twice is harmless.
DROP POLICY IF EXISTS "workflow_templates_read_system" ON public.workflow_templates;
DROP POLICY IF EXISTS "workflow_templates_never_a_system_row_insert" ON public.workflow_templates;
DROP POLICY IF EXISTS "workflow_templates_never_a_system_row_update" ON public.workflow_templates;
DROP POLICY IF EXISTS "workflow_templates_never_a_system_row_delete" ON public.workflow_templates;
DROP POLICY IF EXISTS "firm_isolation" ON public.workflow_templates;
CREATE POLICY "firm_isolation" ON public.workflow_templates
    USING (firm_id = get_my_firm_id() OR is_system = true);

DROP POLICY IF EXISTS "workflow_steps_read" ON public.workflow_steps;
DROP POLICY IF EXISTS "workflow_steps_insert_own_firm" ON public.workflow_steps;
DROP POLICY IF EXISTS "workflow_steps_update_own_firm" ON public.workflow_steps;
DROP POLICY IF EXISTS "workflow_steps_delete_own_firm" ON public.workflow_steps;
DROP POLICY IF EXISTS "firm_isolation_via_template" ON public.workflow_steps;
CREATE POLICY "firm_isolation_via_template" ON public.workflow_steps
    USING (EXISTS (
        SELECT 1 FROM public.workflow_templates t
         WHERE t.id = workflow_steps.template_id
           AND (t.firm_id = get_my_firm_id() OR t.is_system = true)));
