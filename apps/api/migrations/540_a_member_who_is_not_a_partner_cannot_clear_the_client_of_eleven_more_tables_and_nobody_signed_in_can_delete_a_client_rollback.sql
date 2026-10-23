-- Rollback of migration 540: drops the thirteen clearing and moving triggers and the account function, and gives public.clients back
-- the four verbs the migrations had granted the signed-in role (SELECT, INSERT, UPDATE, DELETE). It does not restore the platform's
-- extra TRUNCATE, REFERENCES, TRIGGER and MAINTAIN that production held on the table before 540 (PostgREST issues none of them).
-- THIS RE-OPENS: a member assigned to a client can again take that client off a row of the twelve tables (and the workflow off an
-- onboarding task) and put it in front of the whole firm, any Manager can again move a shared account onto one client, and a
-- Partner's own token can again delete a client row over PostgREST.
-- Like the migration it drops the triggers inside one block, so the table locks are taken in one round trip.
SELECT set_config('lock_timeout', '15s', true);

DO $apply$
BEGIN
  DROP TRIGGER IF EXISTS an_activity_entry_keeps_its_client_unless_a_partner_clears_it ON public.activity_logs;
  DROP TRIGGER IF EXISTS an_ai_evidence_row_keeps_its_client_unless_a_partner_clears_it ON public.ai_evidence;
  DROP TRIGGER IF EXISTS an_ai_signal_keeps_its_client_unless_a_partner_clears_it ON public.ai_signals;
  DROP TRIGGER IF EXISTS a_lifecycle_event_keeps_its_client_unless_a_partner_clears_it ON public.client_lifecycle_events;
  DROP TRIGGER IF EXISTS an_article_keeps_its_client_unless_a_partner_clears_it ON public.knowledge_articles;
  DROP TRIGGER IF EXISTS an_mca_filing_keeps_its_client_unless_a_partner_clears_it ON public.mca_filings;
  DROP TRIGGER IF EXISTS a_proposal_keeps_its_client_unless_a_partner_clears_it ON public.proposals;
  DROP TRIGGER IF EXISTS a_reminder_keeps_its_client_unless_a_partner_clears_it ON public.reminders;
  DROP TRIGGER IF EXISTS a_scheduled_report_keeps_its_client_unless_a_partner_clears_it ON public.scheduled_reports;
  DROP TRIGGER IF EXISTS a_recurring_task_keeps_its_client_unless_a_partner_clears_it ON public.task_recurring_configs;
  DROP TRIGGER IF EXISTS a_time_entry_keeps_its_client_unless_a_partner_clears_it ON public.time_entries;
  DROP TRIGGER IF EXISTS an_onboarding_task_keeps_its_workflow_unless_a_partner_clears ON public.onboarding_tasks;
  DROP TRIGGER IF EXISTS an_account_keeps_its_client_unless_a_partner_changes_it ON public.chart_of_accounts;
END $apply$;

DROP FUNCTION IF EXISTS public.refuse_a_signed_in_member_changing_the_client_of_a_row();

GRANT SELECT, INSERT, UPDATE, DELETE ON public.clients TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.clients TO service_role;
