-- Rollback of migration 529: drops the twenty-two policies it created. Nothing else changes; the firm policies on the
-- twenty-one tables are untouched, so they go back to the firm-wide reading they had. The change in
-- routers/engagement_letters.py (the letter number is read with every letter in view) is harmless without the scope and
-- stays.
--
-- Roll back 529 on its own: it does not depend on 525 to 528, and they do not depend on it.

DROP POLICY IF EXISTS "engagements_assignment_scope" ON public.engagements;
DROP POLICY IF EXISTS "engagements_internal_partner_only" ON public.engagements;
DROP POLICY IF EXISTS "engagement_events_parent_visible" ON public.engagement_events;
DROP POLICY IF EXISTS "credit_note_allocations_parent_visible" ON public.credit_note_allocations;
DROP POLICY IF EXISTS "debit_note_allocations_parent_visible" ON public.debit_note_allocations;
DROP POLICY IF EXISTS "purchase_credit_note_allocations_parent_visible" ON public.purchase_credit_note_allocations;
DROP POLICY IF EXISTS "sales_debit_note_allocations_parent_visible" ON public.sales_debit_note_allocations;
DROP POLICY IF EXISTS "customer_payment_events_parent_visible" ON public.customer_payment_events;
DROP POLICY IF EXISTS "document_extractions_parent_visible" ON public.document_extractions;
DROP POLICY IF EXISTS "itr_filing_versions_parent_visible" ON public.itr_filing_versions;
DROP POLICY IF EXISTS "onboarding_tasks_parent_visible" ON public.onboarding_tasks;
DROP POLICY IF EXISTS "recurring_journal_runs_parent_visible" ON public.recurring_journal_runs;
DROP POLICY IF EXISTS "recurring_purchase_bill_runs_parent_visible" ON public.recurring_purchase_bill_runs;
DROP POLICY IF EXISTS "workflow_approvals_parent_visible" ON public.workflow_approvals;
DROP POLICY IF EXISTS "workflow_executions_parent_visible" ON public.workflow_executions;
DROP POLICY IF EXISTS "workflow_failures_parent_visible" ON public.workflow_failures;
DROP POLICY IF EXISTS "year_end_checklist_items_parent_visible" ON public.year_end_checklist_items;
DROP POLICY IF EXISTS "task_tags_parent_visible" ON public.task_tags;
DROP POLICY IF EXISTS "task_timeline_events_parent_visible" ON public.task_timeline_events;
DO $do$
BEGIN
  IF to_regclass('public.notes_to_accounts') IS NOT NULL THEN
    DROP POLICY IF EXISTS "notes_to_accounts_parent_visible" ON public.notes_to_accounts;
  END IF;
  IF to_regclass('public.year_end_checklists') IS NOT NULL THEN
    DROP POLICY IF EXISTS "year_end_checklists_parent_visible" ON public.year_end_checklists;
  END IF;
  IF to_regclass('public.year_end_reviews') IS NOT NULL THEN
    DROP POLICY IF EXISTS "year_end_reviews_parent_visible" ON public.year_end_reviews;
  END IF;
END
$do$;
