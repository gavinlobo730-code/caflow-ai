-- Migration 529 — the engagement letters take the client's assignment scope and the internal practice's Partner-only guard, and
-- twenty tables that hang from a client table (the four credit and debit note allocations, the engagement letters' events, the
-- payment events, the document extractions, the ITR versions, the onboarding tasks, the recurring-journal and recurring-bill
-- runs, the three workflow logs, the year-end checklist, review and notes tables, and the task tags and timeline) are visible
-- only where the row they hang from is (POST-A-299 `engagements`, POST-A-302, POST-A-305's task tables; the second tranche of the
-- hole 527 named and the catalog rule 528 extended).
--
-- THE HOLE
--
--   `engagements` is an engagement letter: the fee, the scope of work, the signatory and the signing link of a client, or of a
--   LEAD who is not a client yet (`client_id` is nullable for that reason, migration 115). It carried a firm policy and
--   nothing per client, so a member of the firm assigned to NO client could read every letter of the firm over PostgREST,
--   change or delete one, and raise one for a client that is not theirs. The table hangs a log from itself
--   (`engagement_events`) that read through the same bare firm policy.
--
--   Twenty more tables name the row they hang from and not a client, and carry a firm policy and no per-client policy of
--   their own, so the scope of the row they hang from (one that `engagements` gains in this same migration, for the first)
--   never reaches them: reading the child directly returns every client's rows. Each is listed with the row it follows (the
--   catalog rule of 528 found eighteen by their foreign keys; the two task tables carry the column and no foreign key at all):
--
--       engagement_events                  engagements
--       credit_note_allocations            credit_notes AND client_sales_invoices
--       sales_debit_note_allocations       sales_debit_notes AND client_sales_invoices
--       purchase_credit_note_allocations   purchase_credit_notes AND purchase_bills
--       debit_note_allocations             debit_notes AND purchase_bills
--       customer_payment_events            customer_payments (the column is nullable: an event with no payment yet)
--       document_extractions               documents
--       itr_filing_versions                itr_filings
--       onboarding_tasks                   onboarding_workflows (nullable)
--       recurring_journal_runs             recurring_journal_templates, and journal_entries when the run names an entry
--       recurring_purchase_bill_runs       recurring_purchase_bill_templates, and purchase_bills when the run names a bill
--       workflow_approvals, _executions,   workflow_instances
--         _failures
--       year_end_checklist_items,          year_end_engagements
--         year_end_checklists, year_end_reviews
--       notes_to_accounts                  year_end_engagements, and financial_statement_versions when the note names one
--       task_tags, task_timeline_events    tasks (neither column has a foreign key)
--
-- WHAT THIS DOES
--
--   1. On `engagements`: the two RESTRICTIVE FOR ALL policies the other client tables carry, written the way migrations 525 to
--      528 write them (so they are asked once per query and not once per row), in the form of the tables whose client may be
--      NULL:
--
--          engagements_assignment_scope       COALESCE(client_id::text IS NULL OR (SELECT get_my_role()) = 'Partner'
--                                                      OR client_id::text IN (SELECT my_assigned_client_ids()), false)
--          engagements_internal_partner_only  client_id IS NULL OR (SELECT get_my_role()) = 'Partner'
--                                             OR client_id::text IS DISTINCT FROM (SELECT my_internal_client_id())::text
--
--      in the USING and in the WITH CHECK. A letter raised against a lead (no client) stays open to the firm, which is what
--      `assert_client_access(user, None)` and `filter_by_client` already say of it and what the route comments say is
--      deliberate; the `client_id IS NULL OR` branch in the guard is for the reason 528 gives for `properties` (a NULL
--      comparison with a firm that has no internal practice is false, and would hide every lead's letter from, and refuse
--      it to, every non-Partner of such a firm).
--   2. On each of the twenty children: `<table>_parent_visible`, one RESTRICTIVE FOR ALL policy asking that the row it hangs
--      from is one the caller can see (an EXISTS over the parent, read as the caller, so the parent's own scope and guards
--      apply inside it) in the USING and in the WITH CHECK. The four allocation tables hang from TWO rows (a note and the
--      document it is allocated against) and ask both. THREE MORE NAME A SECOND ROW THAT MAY BE ABSENT (a recurring-journal run
--      its journal entry, a recurring-bill run its bill, a note to the accounts its financial statement version): they ask
--      the template or the engagement and, when the column is set, that row too, because a run written under a client's
--      template that names another client's bill would otherwise be a way to learn that a hidden row exists (found by the
--      independent review of this change). A nullable foreign key (`customer_payment_events.payment_id`,
--      `onboarding_tasks.workflow_id`) says `IS NULL OR`, so an event or a task with no parent stays open to the firm as
--      before. A child is exactly as visible as its parents, and cannot be written onto a parent the caller cannot see.
--   3. THREE OF THE TWENTY ARE ABSENT FROM PRODUCTION (`notes_to_accounts`, `year_end_checklists`, `year_end_reviews`: the production
--      snapshot of 03-09-2026 holds none of them, and the live project may or may not have them since) and present in a
--      database built from the migrations. Their policies are created inside a DO block that asks `to_regclass` first, with the name written out
--      as a literal in each statement, so the migration applies to both. A table nobody has cannot be read by anybody.
--
--   Items 1 and 2 narrow the firm policy already there and cannot widen anything. Nothing a Partner can do changes, and nothing
--   an assigned Manager or Executive does for their own clients changes, with ONE exception that this migration is built around:
--
-- THE ONE THING THAT BREAKS, AND THE CHANGE IN THE ROUTE THAT KEEPS IT WORKING
--
--   `routers/engagement_letters._next_engagement_no` allocates the next letter number as the newest number of the firm plus
--   one, and the table has a unique index on (firm_id, engagement_number). It read as the CALLER. Once the table carries the
--   scope, the newest letter a Manager can see is the newest of THEIR clients' letters and the leads', so the next number can be
--   one that another client's letter already holds: the insert fails on the index (a 422 carrying the raw database text) and
--   fails again on every retry, because the Manager's own latest never passes the hidden numbers. Found by reading every
--   reader of the table before writing the scope: with letters 0001 (the Manager's client), 0002 (a lead's) and 0003 (another
--   Manager's client, the newest), the Manager's next number was 0004 before the scope and 0003 after it. The number is a
--   sequence of the FIRM and is now read with the privileged client when there is one (`_numbering_db`), falling back to the
--   caller's own client only where there is no other (mock mode); the route only supplies the number, and every other read
--   of the table is by id after `assert_client_access`. The change ships with this migration and is covered by
--   `tests/test_an_engagement_number_is_allocated_from_every_letter_of_the_firm.py`.
--
--   No screen reads any of the twenty-one tables over PostgREST with a `.from("<table>")`; ONE embeds one, the client's
--   lifecycle page selecting `tasks:onboarding_tasks(*)` under an onboarding workflow, and that follows the workflow it hangs
--   from, which was already scoped. Every route that reaches them asserts the client of the row first, so the lists a member
--   who is not a Partner sees do not change except where a list was a hole (a route that asked for the firm's rows with no
--   client and did not narrow them, or counted them: the workflow analytics counts of a scoped caller were the firm's).
--
--   Every CREATE POLICY below is written out with its name as a literal, on purpose: `test_guards_match_production_pg` excuses a
--   restrictive policy that production does not hold yet only when a migration after its snapshot names it in plain text.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--
--   * The eleven client tables still on the shrink-only list `tests/fixtures/assignment_scope_exceptions.json` (kind `pending`,
--     POST-A-299): the statutory identity, payroll settings and PT registrations (a read-only grant since 519, and an employee or
--     portal branch to keep), the year locks, the FX tables, the stock ledger, the party credit tables, the demo filings and the
--     portal sessions.
--   * The `ri_*` tables (a database built from the migrations has them, production does not): a grant to remove, not a policy,
--     POST-A-305.
--   * Nine parents carry the assignment scope and NOT the internal practice's Partner-only guard (`debit_notes`,
--     `purchase_credit_notes`, `sales_debit_notes`, `onboarding_workflows`, `tasks`, the two recurring templates,
--     `workflow_instances` and `itr_filings`). A child follows its parent, so the rows of the practice's own client under them
--     are exactly as visible as the parent's, which is to a member assigned to the practice: that gap is the parent's, it is
--     not widened here and it is POST-A-306.
--
-- Idempotent (DROP POLICY IF EXISTS before each CREATE). Reversible: 529_..._rollback.sql drops the twenty-two policies, which
-- restores the firm-wide behaviour and nothing else.
--
-- LOCKS. DROP POLICY and CREATE POLICY take an ACCESS EXCLUSIVE lock on their table until the migration commits (it is one
-- transaction); the twenty-one tables are only asked for the policy catalog, not scanned. A lock_timeout of 15 seconds for this
-- transaction (as 525 to 528 set) makes a long-running transaction that holds one of them fail the migration, to be re-run,
-- instead of queueing every later request on the table behind it.

SELECT set_config('lock_timeout', '15s', true);

-- ── engagements: the client and the internal practice ─────────────────────────────────────────────────────────

DROP POLICY IF EXISTS "engagements_assignment_scope" ON public.engagements;
CREATE POLICY "engagements_assignment_scope" ON public.engagements
  AS RESTRICTIVE FOR ALL
  USING (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                   OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false))
  WITH CHECK (COALESCE(((client_id)::text IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
                        OR (client_id)::text IN (SELECT public.my_assigned_client_ids())), false));

DROP POLICY IF EXISTS "engagements_internal_partner_only" ON public.engagements;
CREATE POLICY "engagements_internal_partner_only" ON public.engagements
  AS RESTRICTIVE FOR ALL
  USING ((client_id IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
          OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text))
  WITH CHECK ((client_id IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
               OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text));

-- ── the children: each is visible exactly where the row it hangs from is ───────────────────────────────────────

DROP POLICY IF EXISTS "engagement_events_parent_visible" ON public.engagement_events;
CREATE POLICY "engagement_events_parent_visible" ON public.engagement_events
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.engagements p WHERE p.id = engagement_events.engagement_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.engagements p WHERE p.id = engagement_events.engagement_id));

DROP POLICY IF EXISTS "credit_note_allocations_parent_visible" ON public.credit_note_allocations;
CREATE POLICY "credit_note_allocations_parent_visible" ON public.credit_note_allocations
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.credit_notes p WHERE p.id = credit_note_allocations.credit_note_id)
         AND EXISTS (SELECT 1 FROM public.client_sales_invoices p WHERE p.id = credit_note_allocations.sales_invoice_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.credit_notes p WHERE p.id = credit_note_allocations.credit_note_id)
              AND EXISTS (SELECT 1 FROM public.client_sales_invoices p WHERE p.id = credit_note_allocations.sales_invoice_id));

DROP POLICY IF EXISTS "debit_note_allocations_parent_visible" ON public.debit_note_allocations;
CREATE POLICY "debit_note_allocations_parent_visible" ON public.debit_note_allocations
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.debit_notes p WHERE p.id = debit_note_allocations.debit_note_id)
         AND EXISTS (SELECT 1 FROM public.purchase_bills p WHERE p.id = debit_note_allocations.purchase_bill_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.debit_notes p WHERE p.id = debit_note_allocations.debit_note_id)
              AND EXISTS (SELECT 1 FROM public.purchase_bills p WHERE p.id = debit_note_allocations.purchase_bill_id));

DROP POLICY IF EXISTS "purchase_credit_note_allocations_parent_visible" ON public.purchase_credit_note_allocations;
CREATE POLICY "purchase_credit_note_allocations_parent_visible" ON public.purchase_credit_note_allocations
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.purchase_credit_notes p WHERE p.id = purchase_credit_note_allocations.credit_note_id)
         AND EXISTS (SELECT 1 FROM public.purchase_bills p WHERE p.id = purchase_credit_note_allocations.purchase_bill_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.purchase_credit_notes p WHERE p.id = purchase_credit_note_allocations.credit_note_id)
              AND EXISTS (SELECT 1 FROM public.purchase_bills p WHERE p.id = purchase_credit_note_allocations.purchase_bill_id));

DROP POLICY IF EXISTS "sales_debit_note_allocations_parent_visible" ON public.sales_debit_note_allocations;
CREATE POLICY "sales_debit_note_allocations_parent_visible" ON public.sales_debit_note_allocations
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.sales_debit_notes p WHERE p.id = sales_debit_note_allocations.debit_note_id)
         AND EXISTS (SELECT 1 FROM public.client_sales_invoices p WHERE p.id = sales_debit_note_allocations.sales_invoice_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.sales_debit_notes p WHERE p.id = sales_debit_note_allocations.debit_note_id)
              AND EXISTS (SELECT 1 FROM public.client_sales_invoices p WHERE p.id = sales_debit_note_allocations.sales_invoice_id));

DROP POLICY IF EXISTS "customer_payment_events_parent_visible" ON public.customer_payment_events;
CREATE POLICY "customer_payment_events_parent_visible" ON public.customer_payment_events
  AS RESTRICTIVE FOR ALL
  USING ((customer_payment_events.payment_id IS NULL OR EXISTS (SELECT 1 FROM public.customer_payments p WHERE p.id = customer_payment_events.payment_id)))
  WITH CHECK ((customer_payment_events.payment_id IS NULL OR EXISTS (SELECT 1 FROM public.customer_payments p WHERE p.id = customer_payment_events.payment_id)));

DROP POLICY IF EXISTS "document_extractions_parent_visible" ON public.document_extractions;
CREATE POLICY "document_extractions_parent_visible" ON public.document_extractions
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.documents p WHERE p.id = document_extractions.document_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.documents p WHERE p.id = document_extractions.document_id));

DROP POLICY IF EXISTS "itr_filing_versions_parent_visible" ON public.itr_filing_versions;
CREATE POLICY "itr_filing_versions_parent_visible" ON public.itr_filing_versions
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.itr_filings p WHERE p.id = itr_filing_versions.itr_filing_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.itr_filings p WHERE p.id = itr_filing_versions.itr_filing_id));

DROP POLICY IF EXISTS "onboarding_tasks_parent_visible" ON public.onboarding_tasks;
CREATE POLICY "onboarding_tasks_parent_visible" ON public.onboarding_tasks
  AS RESTRICTIVE FOR ALL
  USING ((onboarding_tasks.workflow_id IS NULL OR EXISTS (SELECT 1 FROM public.onboarding_workflows p WHERE p.id = onboarding_tasks.workflow_id)))
  WITH CHECK ((onboarding_tasks.workflow_id IS NULL OR EXISTS (SELECT 1 FROM public.onboarding_workflows p WHERE p.id = onboarding_tasks.workflow_id)));

DROP POLICY IF EXISTS "recurring_journal_runs_parent_visible" ON public.recurring_journal_runs;
CREATE POLICY "recurring_journal_runs_parent_visible" ON public.recurring_journal_runs
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.recurring_journal_templates p WHERE p.id = recurring_journal_runs.template_id)
         AND (recurring_journal_runs.journal_entry_id IS NULL OR EXISTS (SELECT 1 FROM public.journal_entries p WHERE p.id = recurring_journal_runs.journal_entry_id)))
  WITH CHECK (EXISTS (SELECT 1 FROM public.recurring_journal_templates p WHERE p.id = recurring_journal_runs.template_id)
              AND (recurring_journal_runs.journal_entry_id IS NULL OR EXISTS (SELECT 1 FROM public.journal_entries p WHERE p.id = recurring_journal_runs.journal_entry_id)));

DROP POLICY IF EXISTS "recurring_purchase_bill_runs_parent_visible" ON public.recurring_purchase_bill_runs;
CREATE POLICY "recurring_purchase_bill_runs_parent_visible" ON public.recurring_purchase_bill_runs
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.recurring_purchase_bill_templates p WHERE p.id = recurring_purchase_bill_runs.template_id)
         AND (recurring_purchase_bill_runs.purchase_bill_id IS NULL OR EXISTS (SELECT 1 FROM public.purchase_bills p WHERE p.id = recurring_purchase_bill_runs.purchase_bill_id)))
  WITH CHECK (EXISTS (SELECT 1 FROM public.recurring_purchase_bill_templates p WHERE p.id = recurring_purchase_bill_runs.template_id)
              AND (recurring_purchase_bill_runs.purchase_bill_id IS NULL OR EXISTS (SELECT 1 FROM public.purchase_bills p WHERE p.id = recurring_purchase_bill_runs.purchase_bill_id)));

DROP POLICY IF EXISTS "workflow_approvals_parent_visible" ON public.workflow_approvals;
CREATE POLICY "workflow_approvals_parent_visible" ON public.workflow_approvals
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.workflow_instances p WHERE p.id = workflow_approvals.instance_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.workflow_instances p WHERE p.id = workflow_approvals.instance_id));

DROP POLICY IF EXISTS "workflow_executions_parent_visible" ON public.workflow_executions;
CREATE POLICY "workflow_executions_parent_visible" ON public.workflow_executions
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.workflow_instances p WHERE p.id = workflow_executions.instance_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.workflow_instances p WHERE p.id = workflow_executions.instance_id));

DROP POLICY IF EXISTS "workflow_failures_parent_visible" ON public.workflow_failures;
CREATE POLICY "workflow_failures_parent_visible" ON public.workflow_failures
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.workflow_instances p WHERE p.id = workflow_failures.instance_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.workflow_instances p WHERE p.id = workflow_failures.instance_id));

DROP POLICY IF EXISTS "year_end_checklist_items_parent_visible" ON public.year_end_checklist_items;
CREATE POLICY "year_end_checklist_items_parent_visible" ON public.year_end_checklist_items
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.year_end_engagements p WHERE p.id = year_end_checklist_items.engagement_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.year_end_engagements p WHERE p.id = year_end_checklist_items.engagement_id));

DROP POLICY IF EXISTS "task_tags_parent_visible" ON public.task_tags;
CREATE POLICY "task_tags_parent_visible" ON public.task_tags
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.tasks p WHERE p.id = task_tags.task_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.tasks p WHERE p.id = task_tags.task_id));

DROP POLICY IF EXISTS "task_timeline_events_parent_visible" ON public.task_timeline_events;
CREATE POLICY "task_timeline_events_parent_visible" ON public.task_timeline_events
  AS RESTRICTIVE FOR ALL
  USING (EXISTS (SELECT 1 FROM public.tasks p WHERE p.id = task_timeline_events.task_id))
  WITH CHECK (EXISTS (SELECT 1 FROM public.tasks p WHERE p.id = task_timeline_events.task_id));

-- ── three children whose table a database built from the migrations has and production has not ──────────────
DO $do$
BEGIN
  IF to_regclass('public.notes_to_accounts') IS NOT NULL THEN
    DROP POLICY IF EXISTS "notes_to_accounts_parent_visible" ON public.notes_to_accounts;
    CREATE POLICY "notes_to_accounts_parent_visible" ON public.notes_to_accounts
      AS RESTRICTIVE FOR ALL
      USING (EXISTS (SELECT 1 FROM public.year_end_engagements p WHERE p.id = notes_to_accounts.engagement_id)
             AND (notes_to_accounts.version_id IS NULL OR EXISTS (SELECT 1 FROM public.financial_statement_versions p WHERE p.id = notes_to_accounts.version_id)))
      WITH CHECK (EXISTS (SELECT 1 FROM public.year_end_engagements p WHERE p.id = notes_to_accounts.engagement_id)
                  AND (notes_to_accounts.version_id IS NULL OR EXISTS (SELECT 1 FROM public.financial_statement_versions p WHERE p.id = notes_to_accounts.version_id)));
  END IF;

  IF to_regclass('public.year_end_checklists') IS NOT NULL THEN
    DROP POLICY IF EXISTS "year_end_checklists_parent_visible" ON public.year_end_checklists;
    CREATE POLICY "year_end_checklists_parent_visible" ON public.year_end_checklists
      AS RESTRICTIVE FOR ALL
      USING (EXISTS (SELECT 1 FROM public.year_end_engagements p WHERE p.id = year_end_checklists.engagement_id))
      WITH CHECK (EXISTS (SELECT 1 FROM public.year_end_engagements p WHERE p.id = year_end_checklists.engagement_id));
  END IF;

  IF to_regclass('public.year_end_reviews') IS NOT NULL THEN
    DROP POLICY IF EXISTS "year_end_reviews_parent_visible" ON public.year_end_reviews;
    CREATE POLICY "year_end_reviews_parent_visible" ON public.year_end_reviews
      AS RESTRICTIVE FOR ALL
      USING (EXISTS (SELECT 1 FROM public.year_end_engagements p WHERE p.id = year_end_reviews.engagement_id))
      WITH CHECK (EXISTS (SELECT 1 FROM public.year_end_engagements p WHERE p.id = year_end_reviews.engagement_id));
  END IF;
END
$do$;
