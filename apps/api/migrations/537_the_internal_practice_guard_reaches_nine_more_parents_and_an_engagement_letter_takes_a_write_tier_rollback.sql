-- Rollback of migration 537: drops the nine internal-practice guards, the six engagement write-tier policies and the four
-- triggers with their function, and puts the two assignment policies back as migration 530 left them.
-- THIS RE-OPENS FOUR THINGS: a member assigned to the internal practice (only by a direct insert into the assignment table)
-- reads and writes the practice's rows in the nine parent tables again; a Reviewer, or a member with the Client role, assigned
-- to a client can again update or delete that client's engagement letter and its events over PostgREST, and a member assigned
-- to nothing can again delete a lead's letter; a member who is not a Partner can again clear the client of a letter,
-- property or Tally job, or the payment of a payment event, which puts the row in the part open to the whole firm; and a
-- Partner's direct insert can again assign the internal practice to a non-Partner.
SELECT set_config('lock_timeout', '15s', true);

ALTER POLICY "partners_insert_assignments" ON public.user_client_assignments
  WITH CHECK (
    firm_id = (SELECT public.get_my_firm_id())
    AND (SELECT public.my_permission('assignment', 'write', 'Partner'))
    AND (SELECT public.user_is_in_my_firm(user_id))
    AND (SELECT public.client_is_in_my_firm(client_id))
  );

ALTER POLICY "partners_update_assignments" ON public.user_client_assignments
  WITH CHECK (
    firm_id = (SELECT public.get_my_firm_id())
    AND (SELECT public.my_permission('assignment', 'write', 'Partner'))
    AND (SELECT public.user_is_in_my_firm(user_id))
    AND (SELECT public.client_is_in_my_firm(client_id))
  );

DROP POLICY IF EXISTS "debit_notes_internal_partner_only" ON public.debit_notes;
DROP POLICY IF EXISTS "purchase_credit_notes_internal_partner_only" ON public.purchase_credit_notes;
DROP POLICY IF EXISTS "sales_debit_notes_internal_partner_only" ON public.sales_debit_notes;
DROP POLICY IF EXISTS "onboarding_workflows_internal_partner_only" ON public.onboarding_workflows;
DROP POLICY IF EXISTS "tasks_internal_partner_only" ON public.tasks;
DROP POLICY IF EXISTS "recurring_journal_templates_internal_partner_only" ON public.recurring_journal_templates;
DROP POLICY IF EXISTS "recurring_purchase_bill_templates_internal_partner_only" ON public.recurring_purchase_bill_templates;
DROP POLICY IF EXISTS "workflow_instances_internal_partner_only" ON public.workflow_instances;
DROP POLICY IF EXISTS "itr_filings_internal_partner_only" ON public.itr_filings;

DROP POLICY IF EXISTS "engagements_write_tier_insert" ON public.engagements;
DROP POLICY IF EXISTS "engagements_write_tier_update" ON public.engagements;
DROP POLICY IF EXISTS "engagements_write_tier_delete" ON public.engagements;
DROP POLICY IF EXISTS "engagement_events_write_tier_insert" ON public.engagement_events;
DROP POLICY IF EXISTS "engagement_events_write_tier_update" ON public.engagement_events;
DROP POLICY IF EXISTS "engagement_events_write_tier_delete" ON public.engagement_events;

DROP TRIGGER IF EXISTS a_letter_keeps_its_client_unless_a_partner_clears_it ON public.engagements;
DROP TRIGGER IF EXISTS a_payment_event_keeps_its_payment_unless_a_partner_clears_it ON public.customer_payment_events;
DROP TRIGGER IF EXISTS a_property_keeps_its_client_unless_a_partner_clears_it ON public.properties;
DROP TRIGGER IF EXISTS a_tally_job_keeps_its_client_unless_a_partner_clears_it ON public.tally_migration_jobs;
DROP FUNCTION IF EXISTS public.refuse_a_signed_in_member_clearing_the_parent_of_a_row();
