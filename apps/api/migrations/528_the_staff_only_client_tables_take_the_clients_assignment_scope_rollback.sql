-- Rollback of migration 528: drops the twenty-seven policies it created and puts knowledge_articles' internal-practice guard
-- back to the expression migration 079 gave it. Nothing else changes; the firm policy and the role tiers on writes are
-- untouched, so the tables go back to the firm-wide reading they had.
--
-- Roll back 528 on its own: it does not depend on 525, 526 or 527, and they do not depend on it.

DROP POLICY IF EXISTS "ais_uploads_assignment_scope" ON public.ais_uploads;
DROP POLICY IF EXISTS "ais_uploads_internal_partner_only" ON public.ais_uploads;
DROP POLICY IF EXISTS "ais_records_assignment_scope" ON public.ais_records;
DROP POLICY IF EXISTS "ais_records_internal_partner_only" ON public.ais_records;
DROP POLICY IF EXISTS "ais_reconciliations_assignment_scope" ON public.ais_reconciliations;
DROP POLICY IF EXISTS "ais_reconciliations_internal_partner_only" ON public.ais_reconciliations;
DROP POLICY IF EXISTS "income_tax_asset_blocks_assignment_scope" ON public.income_tax_asset_blocks;
DROP POLICY IF EXISTS "income_tax_asset_blocks_internal_partner_only" ON public.income_tax_asset_blocks;
DROP POLICY IF EXISTS "schedule_iii_ratio_explanations_assignment_scope" ON public.schedule_iii_ratio_explanations;
DROP POLICY IF EXISTS "schedule_iii_ratio_explanations_internal_partner_only" ON public.schedule_iii_ratio_explanations;
DROP POLICY IF EXISTS "schedule_iii_ratio_inputs_assignment_scope" ON public.schedule_iii_ratio_inputs;
DROP POLICY IF EXISTS "schedule_iii_ratio_inputs_internal_partner_only" ON public.schedule_iii_ratio_inputs;
DROP POLICY IF EXISTS "schedule_iii_unbilled_reviews_assignment_scope" ON public.schedule_iii_unbilled_reviews;
DROP POLICY IF EXISTS "schedule_iii_unbilled_reviews_internal_partner_only" ON public.schedule_iii_unbilled_reviews;
DROP POLICY IF EXISTS "properties_assignment_scope" ON public.properties;
DROP POLICY IF EXISTS "properties_internal_partner_only" ON public.properties;
DROP POLICY IF EXISTS "recurring_invoice_templates_assignment_scope" ON public.recurring_invoice_templates;
DROP POLICY IF EXISTS "recurring_invoice_templates_internal_partner_only" ON public.recurring_invoice_templates;
DROP POLICY IF EXISTS "onboarding_checklists_assignment_scope" ON public.onboarding_checklists;
DROP POLICY IF EXISTS "onboarding_checklists_internal_partner_only" ON public.onboarding_checklists;
DROP POLICY IF EXISTS "tally_migration_jobs_assignment_scope" ON public.tally_migration_jobs;
DROP POLICY IF EXISTS "tally_migration_jobs_internal_partner_only" ON public.tally_migration_jobs;
DROP POLICY IF EXISTS "ais_records_parent_visible" ON public.ais_records;
DROP POLICY IF EXISTS "ais_reconciliations_parent_visible" ON public.ais_reconciliations;
DROP POLICY IF EXISTS "tally_migration_items_parent_visible" ON public.tally_migration_items;
DROP POLICY IF EXISTS "onboarding_checklist_steps_parent_visible" ON public.onboarding_checklist_steps;
DROP POLICY IF EXISTS "recurring_invoice_runs_parent_visible" ON public.recurring_invoice_runs;

ALTER POLICY "knowledge_articles_internal_partner_only" ON public.knowledge_articles
  USING (((SELECT public.get_my_role()) = 'Partner'::text
          OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text))
  WITH CHECK (((SELECT public.get_my_role()) = 'Partner'::text
               OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text));
