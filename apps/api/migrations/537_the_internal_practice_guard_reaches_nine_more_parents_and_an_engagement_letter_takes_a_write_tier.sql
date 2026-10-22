-- Migration 537 — the internal practice's Partner-only guard reaches nine more parent tables and the assignment table itself
-- refuses to assign the practice, an engagement letter and its events take a role tier on writes, and a signed-in member who is
-- not a Partner can no longer move a row into the part of a table that is open to the whole firm by clearing its client
-- (POST-A-306, POST-A-309).
--
-- THE HOLES
--
--   1. POST-A-306. The internal practice (`clients.is_internal`, the firm's own books) is a Partner's alone (G1). Migration 074
--      gave every client table of its day a RESTRICTIVE `<table>_internal_partner_only` policy, and migrations 527 and 528 gave
--      one to every table they scoped. Nine PARENT tables were scoped by migration 084 or by 370 and never got it:
--
--          debit_notes  purchase_credit_notes  sales_debit_notes  onboarding_workflows  tasks
--          recurring_journal_templates  recurring_purchase_bill_templates  workflow_instances  itr_filings
--
--      so the practice's own debit notes, tasks, onboarding and workflow instances and returns are visible, and writable, to a
--      member who has a `user_client_assignments` row for the practice. `routers/assignments.py` refuses to create one and
--      migration 478 restricted the table to Partners, so a row can exist only through a direct insert by a Partner: a gap in
--      depth and not a live leak. The twenty children of migration 529 follow their parents exactly, so closing the nine
--      closes the rows under them as well (the children of `engagements`, `credit_notes`, `client_sales_invoices`,
--      `purchase_bills`, `customer_payments`, `documents` and `year_end_engagements` already followed a guarded parent).
--      The same gap is on the assignment table itself, found by the review of migration 530: its insert and update policies
--      ask that the member and the client belong to the firm and say nothing about the practice, so a Partner's direct insert
--      assigns a non-Partner to the practice, after which the member reads its customers and the rest of the ~110 assignment-
--      scoped tables that never took the guard at all (production held no such assignment row when the table was read on 22-10-2026).
--
--   2. POST-A-309 (1). `engagements` (an engagement letter: the fee, the scope, the signatory and the signing link) and
--      `engagement_events` carry a firm policy, the assignment scope (529) and nothing that asks a ROLE, while every route that
--      writes them asks `client:write`, which is a Manager's by default (`core/permissions.py`). So a Reviewer, or a member
--      with the Client role, assigned to a client could update or delete that client's letter straight over PostgREST, and a
--      member assigned to nothing could delete a LEAD's letter (a letter with no client is open to the firm by design). The
--      tables of migrations 488 and 489 carry such a tier; these two did not.
--
--   3. POST-A-309 (2). A row whose client may be NULL is open to the whole firm when it is (`engagements`: a letter raised
--      against a lead; `properties` and `tally_migration_jobs`: a firm-level row; `customer_payment_events`: an event with no
--      payment yet). The assignment policies admit that row to every member and their WITH CHECK admits writing it, so a member
--      assigned to a client could `UPDATE ... SET client_id = NULL` on that client's letter, property or Tally job (or
--      `payment_id = NULL` on a payment event, which carries the gateway's raw payload) and put it in front of every other
--      member of the firm. The same thing happens when the client row is deleted (`fk_engagements_client` is ON DELETE SET
--      NULL), which no signed-in session can do (the API deletes a client by marking it, and the one statement that removes
--      client rows is the firm purge).
--
-- WHAT THIS DOES
--
--   1. The nine `<table>_internal_partner_only` policies, RESTRICTIVE FOR ALL, in the form of migrations 527 and 528 (the role
--      and the practice's id are asked once per query, in a (SELECT ...), and the WITH CHECK is the USING, so a write is judged
--      by the rule a read is). Eight of the nine tables have `client_id NOT NULL` and take the plain form; `workflow_instances`
--      is nullable (a workflow can run for the firm), so its guard says `client_id IS NULL OR` for the reason 528 gives for
--      `properties`: in a firm with no internal practice the comparison is `NULL IS DISTINCT FROM NULL`, which is false, and
--      would hide every client-less row from the members its own assignment policy admits it to.
--   2. `partners_insert_assignments` and `partners_update_assignments` (the policies of 478 as 530 left them) gain
--      `client_id IS DISTINCT FROM (SELECT my_internal_client_id())` in the WITH CHECK, so no signed-in session can assign the
--      practice to anybody, which is what `routers/assignments.py` already answers with a 400 (G1). With the source closed, the
--      member who reads the practice's rows in a table that never took the guard cannot come to exist through the API or
--      PostgREST. The delete policy is untouched (a stale row can still be removed) and so is the privileged client, which
--      the API's own check judges; the pg tests of the guards assign the practice as the database owner, as they did.
--   3. `engagements_write_tier_insert/_update/_delete` and `engagement_events_write_tier_insert/_update/_delete`: RESTRICTIVE,
--      FOR each command, TO authenticated, `my_permission('client', 'write', 'Manager')`, the pair every route asks (an
--      Executive or a Reviewer a Partner has granted `client:write` to in the per-person grid still passes: `my_permission`
--      honours the grid). Reads are unchanged (`client:read` is every staff role). A lead's letter stays writable by whoever
--      may write letters, which is the same pair.
--   4. `refuse_a_signed_in_member_clearing_the_parent_of_a_row`, a BEFORE UPDATE trigger on the four columns above: a signed-in
--      session (`current_setting('role')` is `authenticated` or `anon`, the test migration 498 uses) whose member is not a
--      Partner may not change a column from a value to NULL. Setting it FROM NULL to a value stays allowed (a lead's letter
--      linked to the client just made, `routers/lifecycle._link_signed_letter`), and so does every write that does not
--      clear it. A Partner may clear it (a lead's letter that needs the client taken off is a Partner's decision, as the
--      ledger put it). The API itself never clears one of these columns (the letter routes do not name `client_id` on an
--      update, `payment_service` writes an event once with its payment, the Tally and property routes set the client when
--      they create the row), and the privileged client and the database owner are not judged: `current_setting('role')` is
--      the owner's there, and the firm purge sets `session_replication_role = replica`, which skips the trigger.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--
--   * The ~110 other tables that carry the assignment scope and not the per-table practice guard (`tax_audits`, `filings`,
--     `capital_gains`, `time_entries`, ...): migration 074 listed the tables of its day and nothing has asserted since that a
--     table scoped later joined it, so the ledger's "the others of this family have both" held for the family it was written
--     about and not for the whole database. They are not given nine more policies each: the practice can no longer be assigned
--     through the API or PostgREST (item 2), and a per-table guard exists to answer an assignment row that cannot now be made.
--     A change to `my_assigned_client_ids()` and `can_access_client()` that stopped counting the practice for a non-Partner
--     would close even a row the privileged client inserted, at the price of changing what every scoped read returns; it is
--     not made here.
--   * The other tables whose client may be NULL (`time_entries`, `reminders`, `proposals`, `tasks`' siblings, the AI tables):
--     the same "clear the client to open the row to the firm" move is possible on each and is filed as POST-A-326.
--     `onboarding_tasks.workflow_id` is the same shape and is in that item too.
--   * Reads of the nine tables by a Partner, and every write a Manager or Executive makes for a client they are assigned to:
--     nothing a person could do through the API changes, because the API refuses an assignment to the practice, asks
--     `client:write` before every letter write, and never clears a client.
--
-- Idempotent (DROP POLICY / DROP TRIGGER IF EXISTS before each CREATE; ALTER POLICY and CREATE OR REPLACE are repeatable).
-- Reversible: 537_..._rollback.sql drops the fifteen policies, the four triggers and the function and puts the two assignment
-- policies back as 530 left them.
--
-- Every CREATE POLICY below is written out with its name as a literal, on purpose: `test_guards_match_production_pg` excuses a
-- restrictive policy production does not hold yet only when a migration after its snapshot names it in plain text.
--
-- LOCKS. DROP POLICY, CREATE POLICY and CREATE TRIGGER take an ACCESS EXCLUSIVE lock (SHARE ROW EXCLUSIVE for the trigger) on
-- their table until the migration commits (it is one transaction); nothing is scanned. A lock_timeout of 15 seconds, as 525 to
-- 536 set, makes a long-running transaction that holds one of the tables fail the migration, to be re-run, instead of queueing
-- every later request on it behind it.

SELECT set_config('lock_timeout', '15s', true);

-- ── 1. the internal practice's Partner-only guard on nine parents ───────────────────────────────────────────

DROP POLICY IF EXISTS "debit_notes_internal_partner_only" ON public.debit_notes;
CREATE POLICY "debit_notes_internal_partner_only" ON public.debit_notes
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

DROP POLICY IF EXISTS "purchase_credit_notes_internal_partner_only" ON public.purchase_credit_notes;
CREATE POLICY "purchase_credit_notes_internal_partner_only" ON public.purchase_credit_notes
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

DROP POLICY IF EXISTS "sales_debit_notes_internal_partner_only" ON public.sales_debit_notes;
CREATE POLICY "sales_debit_notes_internal_partner_only" ON public.sales_debit_notes
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

DROP POLICY IF EXISTS "onboarding_workflows_internal_partner_only" ON public.onboarding_workflows;
CREATE POLICY "onboarding_workflows_internal_partner_only" ON public.onboarding_workflows
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

DROP POLICY IF EXISTS "tasks_internal_partner_only" ON public.tasks;
CREATE POLICY "tasks_internal_partner_only" ON public.tasks
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

DROP POLICY IF EXISTS "recurring_journal_templates_internal_partner_only" ON public.recurring_journal_templates;
CREATE POLICY "recurring_journal_templates_internal_partner_only" ON public.recurring_journal_templates
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

DROP POLICY IF EXISTS "recurring_purchase_bill_templates_internal_partner_only" ON public.recurring_purchase_bill_templates;
CREATE POLICY "recurring_purchase_bill_templates_internal_partner_only" ON public.recurring_purchase_bill_templates
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

DROP POLICY IF EXISTS "itr_filings_internal_partner_only" ON public.itr_filings;
CREATE POLICY "itr_filings_internal_partner_only" ON public.itr_filings
  AS RESTRICTIVE FOR ALL
  USING ((SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK ((SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- workflow_instances.client_id is nullable: a workflow can run for the firm, and that row stays open to the firm
DROP POLICY IF EXISTS "workflow_instances_internal_partner_only" ON public.workflow_instances;
CREATE POLICY "workflow_instances_internal_partner_only" ON public.workflow_instances
  AS RESTRICTIVE FOR ALL
  USING (client_id IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
         OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text)
  WITH CHECK (client_id IS NULL OR (SELECT public.get_my_role()) = 'Partner'::text
              OR (client_id)::text IS DISTINCT FROM ((SELECT public.my_internal_client_id()))::text);

-- ── 1b. the practice is not assigned to anybody by a signed-in session ──────────────────────────────────────────

ALTER POLICY "partners_insert_assignments" ON public.user_client_assignments
  WITH CHECK (
    firm_id = (SELECT public.get_my_firm_id())
    AND (SELECT public.my_permission('assignment', 'write', 'Partner'))
    AND (SELECT public.user_is_in_my_firm(user_id))
    AND (SELECT public.client_is_in_my_firm(client_id))
    AND client_id IS DISTINCT FROM (SELECT public.my_internal_client_id())
  );

ALTER POLICY "partners_update_assignments" ON public.user_client_assignments
  WITH CHECK (
    firm_id = (SELECT public.get_my_firm_id())
    AND (SELECT public.my_permission('assignment', 'write', 'Partner'))
    AND (SELECT public.user_is_in_my_firm(user_id))
    AND (SELECT public.client_is_in_my_firm(client_id))
    AND client_id IS DISTINCT FROM (SELECT public.my_internal_client_id())
  );

-- ── 2. an engagement letter and its events take the role tier the routes already ask ─────────────────────────

DROP POLICY IF EXISTS "engagements_write_tier_insert" ON public.engagements;
CREATE POLICY "engagements_write_tier_insert" ON public.engagements
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK ((SELECT public.my_permission('client', 'write', 'Manager')));

DROP POLICY IF EXISTS "engagements_write_tier_update" ON public.engagements;
CREATE POLICY "engagements_write_tier_update" ON public.engagements
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING ((SELECT public.my_permission('client', 'write', 'Manager')))
  WITH CHECK ((SELECT public.my_permission('client', 'write', 'Manager')));

DROP POLICY IF EXISTS "engagements_write_tier_delete" ON public.engagements;
CREATE POLICY "engagements_write_tier_delete" ON public.engagements
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING ((SELECT public.my_permission('client', 'write', 'Manager')));

DROP POLICY IF EXISTS "engagement_events_write_tier_insert" ON public.engagement_events;
CREATE POLICY "engagement_events_write_tier_insert" ON public.engagement_events
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK ((SELECT public.my_permission('client', 'write', 'Manager')));

DROP POLICY IF EXISTS "engagement_events_write_tier_update" ON public.engagement_events;
CREATE POLICY "engagement_events_write_tier_update" ON public.engagement_events
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING ((SELECT public.my_permission('client', 'write', 'Manager')))
  WITH CHECK ((SELECT public.my_permission('client', 'write', 'Manager')));

DROP POLICY IF EXISTS "engagement_events_write_tier_delete" ON public.engagement_events;
CREATE POLICY "engagement_events_write_tier_delete" ON public.engagement_events
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING ((SELECT public.my_permission('client', 'write', 'Manager')));

-- ── 3. only a Partner may clear the client (or the payment) of a row that is then open to the whole firm ──────

CREATE OR REPLACE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_role   text := COALESCE(current_setting('role', true), 'none');
    v_column text := TG_ARGV[0];
BEGIN
    IF v_role IN ('authenticated', 'anon')
       AND (to_jsonb(OLD) ->> v_column) IS NOT NULL
       AND (to_jsonb(NEW) ->> v_column) IS NULL
       AND COALESCE((SELECT public.get_my_role()), '') <> 'Partner'
    THEN
        RAISE EXCEPTION
            'Only a Partner can take the % off a % row: a row with none is open to every member of the firm. Nothing was changed.',
            v_column, TG_TABLE_NAME
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row() IS
    'POST-A-309. A signed-in session whose member is not a Partner may not change client_id (or payment_id) from a value to '
    'NULL on engagements, customer_payment_events, properties and tally_migration_jobs: a row with none is open to the whole '
    'firm. Migration 537.';

REVOKE ALL ON FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS a_letter_keeps_its_client_unless_a_partner_clears_it ON public.engagements;
CREATE TRIGGER a_letter_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.engagements
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

DROP TRIGGER IF EXISTS a_payment_event_keeps_its_payment_unless_a_partner_clears_it ON public.customer_payment_events;
CREATE TRIGGER a_payment_event_keeps_its_payment_unless_a_partner_clears_it
    BEFORE UPDATE OF payment_id ON public.customer_payment_events
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('payment_id');

DROP TRIGGER IF EXISTS a_property_keeps_its_client_unless_a_partner_clears_it ON public.properties;
CREATE TRIGGER a_property_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.properties
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

DROP TRIGGER IF EXISTS a_tally_job_keeps_its_client_unless_a_partner_clears_it ON public.tally_migration_jobs;
CREATE TRIGGER a_tally_job_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.tally_migration_jobs
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

-- ── 4. the migration checks its own result ─────────────────────────────────────────────────────────────────────

DO $$
DECLARE
    n_guards   int;
    n_tiers    int;
    n_triggers int;
    n_assign   int;
    n_rows     bigint;
BEGIN
    SELECT count(*) INTO n_guards
      FROM pg_policy p
     WHERE NOT p.polpermissive AND p.polcmd = '*'
       AND p.polname IN ('debit_notes_internal_partner_only', 'purchase_credit_notes_internal_partner_only',
                         'sales_debit_notes_internal_partner_only', 'onboarding_workflows_internal_partner_only',
                         'tasks_internal_partner_only', 'recurring_journal_templates_internal_partner_only',
                         'recurring_purchase_bill_templates_internal_partner_only', 'workflow_instances_internal_partner_only',
                         'itr_filings_internal_partner_only');
    IF n_guards <> 9 THEN
        RAISE EXCEPTION 'migration 537: expected 9 internal-practice guards, found %', n_guards;
    END IF;

    SELECT count(*) INTO n_tiers
      FROM pg_policy p
     WHERE NOT p.polpermissive
       AND p.polname IN ('engagements_write_tier_insert', 'engagements_write_tier_update', 'engagements_write_tier_delete',
                         'engagement_events_write_tier_insert', 'engagement_events_write_tier_update',
                         'engagement_events_write_tier_delete');
    IF n_tiers <> 6 THEN
        RAISE EXCEPTION 'migration 537: expected 6 write-tier policies, found %', n_tiers;
    END IF;

    SELECT count(*) INTO n_triggers
      FROM pg_trigger t
     WHERE NOT t.tgisinternal AND t.tgenabled = 'O'
       AND t.tgname IN ('a_letter_keeps_its_client_unless_a_partner_clears_it',
                        'a_payment_event_keeps_its_payment_unless_a_partner_clears_it',
                        'a_property_keeps_its_client_unless_a_partner_clears_it',
                        'a_tally_job_keeps_its_client_unless_a_partner_clears_it');
    IF n_triggers <> 4 THEN
        RAISE EXCEPTION 'migration 537: expected 4 enabled triggers, found %', n_triggers;
    END IF;

    SELECT count(*) INTO n_assign
      FROM pg_policy p
     WHERE p.polrelid = 'public.user_client_assignments'::regclass
       AND p.polname IN ('partners_insert_assignments', 'partners_update_assignments')
       AND pg_get_expr(p.polwithcheck, p.polrelid) LIKE '%my_internal_client_id%';
    IF n_assign <> 2 THEN
        RAISE EXCEPTION 'migration 537: expected the 2 assignment policies to refuse the practice, found %', n_assign;
    END IF;

    SELECT count(*) INTO n_rows
      FROM public.user_client_assignments a
      JOIN public.firms f ON f.id = a.firm_id AND f.internal_client_id = a.client_id;
    IF n_rows > 0 THEN
        RAISE WARNING 'migration 537: % assignment row(s) already name a firm''s internal practice; they are left in place (the delete policy is untouched) and a Partner should remove them', n_rows;
    END IF;

    IF has_function_privilege('authenticated', 'public.refuse_a_signed_in_member_clearing_the_parent_of_a_row()', 'EXECUTE')
       OR has_function_privilege('anon', 'public.refuse_a_signed_in_member_clearing_the_parent_of_a_row()', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 537: the trigger function is executable by a browser role';
    END IF;
END $$;
