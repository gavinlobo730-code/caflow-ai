-- Migration 540 — a signed-in member who is not a Partner can no longer clear the client of eleven more tables (or the workflow
-- of an onboarding task) or move a shared account onto one client, and the signed-in role can no longer delete a client row
-- (POST-A-326, POST-A-303).
--
-- THE HOLES
--
--   1. POST-A-326. Migration 537 closed one move on four tables: a member assigned to a client sets that client's row to NO client
--      (`UPDATE ... SET client_id = NULL`), and the assignment scope, which admits a client-less row to every member of the firm
--      (migration 084, kept by the 526 rewrite), then shows it to everybody. The same move was open on every other table whose
--      client may be NULL and whose signed-in role holds UPDATE on that column. Read from a database built from the migrations and
--      from production on 23-10-2026 (each of the twelve below grants UPDATE to `authenticated`, among the other write verbs,
--      and none had a trigger of that kind):
--
--          activity_logs  ai_evidence  ai_signals  client_lifecycle_events  knowledge_articles  mca_filings
--          proposals  reminders  scheduled_reports  task_recurring_configs  time_entries  chart_of_accounts
--
--      plus the child column `onboarding_tasks.workflow_id`, whose policy lets a task with NO workflow be read by the firm (a
--      task whose workflow is cleared stops following the workflow's client). `knowledge_articles` was found by the review of this
--      migration: its restrictive policy is named `_assignment`, not `_assignment_scope`, and admits `client_id IS NULL`, so a
--      Manager (who reads every article already) could clear a client's article and show it to the Executives and Reviewers who
--      are not assigned to that client. `ai_recommendations` and `workflow_instances` also have a nullable client behind the scope,
--      but the signed-in role holds no write on either (migrations 505 and 509), and `notifications` has a nullable client but is
--      read by its recipient and not by the client's assignees. The four rows 537 guarded are `engagements`, `properties`,
--      `tally_migration_jobs` and `customer_payment_events.payment_id`.
--
--      `chart_of_accounts` is the one where the harm is more than a read, and in BOTH directions. A row with no client is a
--      firm-level account that any of the firm's entries may use (migration 360), and production's chart is almost all firm-level (133
--      accounts, 2 with a client, per 360's header). Clearing a client's account puts it in every other client's chart; the
--      opposite move, setting a shared account's client to one client, takes it away from every other client, whose postings
--      to it are then refused by 360's own trigger until a Partner moves it back. No flow fills the column on an existing account
--      (the account PATCH has no client field and the chart import and the seed services only insert). So the chart takes its own
--      function: any change of `client_id` by a signed-in session whose member is not a Partner is refused.
--
--   2. POST-A-303. The signed-in role holds DELETE on `clients` (migrations 010 and 041; a Partner-tier policy since 260, the
--      per-person grid since 415). The API never deletes a client row (its delete is a soft delete, and the firm purge is the only
--      statement that removes client rows), and nothing in apps/web does, so the privilege is used by nobody, but a Partner's
--      own token, or the token of a member the grid gave `client:delete`, can delete a client over PostgREST that has no row in
--      any NO ACTION table (a client with a ledger, a document, a task, a filing or bank data is refused by the foreign key).
--      For such a client the delete CASCADES into 138 child tables on a database built from the migrations (production's count
--      is not readable from here), among them tables the signed-in role cannot delete from (a foreign-key cascade is not a
--      privilege check, migration 499's header says so), and three foreign keys are ON DELETE SET NULL:
--      `tally_migration_jobs.client_id` and `engagements.client_id` turn the rows into firm-wide ones (the jobs and the parsed
--      ledgers, customers and vendors under them are then read by every member), and `firms.internal_client_id` points nowhere.
--      Only a Partner passes the existing guards, which is why it is low.
--
-- WHAT THIS DOES
--
--   1. The trigger function of 537, `refuse_a_signed_in_member_clearing_the_parent_of_a_row()`, is attached
--      to the twelve columns above other than the chart's, as BEFORE UPDATE OF <column>: a signed-in session
--      (`current_setting('role')` is `authenticated` or `anon`) whose member is not a Partner may not change the column from a
--      value to NULL (42501 and a sentence). Setting it FROM NULL to a value stays allowed, so does every write that does not
--      clear it, a write that leaves a NULL column NULL, and a write that names the column and sends the value it already has
--      (the mark-sent route of `reminders` re-sends the whole row it read). A Partner may clear it, as in 537. The privileged
--      client, the database owner and the firm purge (replica mode) are not judged. That function is unchanged, so nothing is
--      restated.
--   2. A new function, `refuse_a_signed_in_member_changing_the_client_of_a_row()`, on `chart_of_accounts.client_id` alone, refuses ANY change of the
--      column (a value to NULL, NULL to a value, one client to another) by the same people and spares the same ones.
--   3. `public.clients` loses everything the signed-in role and the anonymous role held except what is used: DELETE, TRUNCATE,
--      REFERENCES, TRIGGER (and MAINTAIN where the platform grants it) go from `authenticated`, `anon` and PUBLIC, and
--      `authenticated` keeps SELECT, INSERT and UPDATE (the browser reads, inserts and updates clients, and the API reads and
--      updates them under the caller's own sign-in), the shape of 535 and 538. The service role keeps its four, explicitly. The
--      ACL was read in production on 23-10-2026: every grant on the table, and no column privilege, was made by `postgres`, the
--      role the runner connects as, so the REVOKE removes what it names (a grant made by another role would make the closing
--      check below fail and roll the whole migration back). The policies are not touched: `clients_role_delete` and the others
--      stay as the second lock, so a privilege handed back later (a dashboard change, a platform default) is still refused to all
--      but a Partner.
--
-- WHAT WAS CHECKED BEFORE ADDING THE RULE, BECAUSE IT COULD HAVE BROKEN A ROUTE
--
--   Four read-only readers went through the writers table by table (the table-use scanner over apps/api, a search of apps/web
--   for `.from()` and every API wrapper, every SQL function and trigger, every foreign-key action), and two further readers reviewed
--   the migration, and none found a path that clears one of the columns as a signed-in session. activity_logs, ai_evidence and
--   ai_signals have no writer at all. chart_of_accounts is written by the API through the privileged client and no UPDATE names
--   `client_id`; the browser's one direct write is an INSERT (the chart import). client_lifecycle_events is insert-only.
--   knowledge_articles is inserted with its client and updated for its version and `is_archived` only. mca_filings is updated for
--   status, SRN, filed date and acknowledgement only. proposals for status and notes. reminders is updated by the mark-sent route
--   with the whole row it read, so the client goes back with the value it had. scheduled_reports is toggled for `is_active` by
--   the browser. task_recurring_configs: the PUT drops null fields, so it cannot clear the client (it CAN move a configuration to
--   another client, which this does not refuse). time_entries: the update model has no client field. onboarding_tasks: both
--   inserts set the workflow and the one update never names it. No foreign key on these columns is ON DELETE SET NULL, so no
--   cascade can clear one. For `clients`: the scanner found 12 writes, all inserts or updates; the soft delete is an UPDATE;
--   the application code in apps/web has 29 `.from("clients")` sites in 27 files, which select, insert (two sites: the client
--   form and the CSV import) and update (one); the firm purge is SECURITY DEFINER and executable by the service role only and
--   was run after the REVOKE in a copy. Not read: anything outside this repository that holds a member's token (a dashboard SQL
--   editor, another service). The triggers and the revoke would affect it, and they are the reason for the change.
--
-- WHAT IT DOES NOT DO, ON PURPOSE
--
--   * The copy-and-delete variant of the same move (insert a client-less copy of a row the member can read, then delete the
--     original) is stopped by no trigger and stays open wherever a tier admits a client-less insert (POST-A-326 names it).
--   * A Partner can still clear the column. That is a Partner's decision, as in 537. Filling a NULL stays allowed on the eleven
--     tables other than the chart: it takes one firm-level row for one client, which is that client's own row, and the two
--     moves that matter (a shared account) are the chart's.
--   * `task_recurring_configs` can still be moved from one client to another by a member who may write both (the route checks both
--     ends); the trigger refuses only a clear.
--   * The signed-in roles keep the platform's other privileges on the twelve tables (TRUNCATE, REFERENCES, TRIGGER); PostgREST
--     issues none of them. Closing the write grants on the three tables nothing writes (`activity_logs`, `ai_evidence`,
--     `ai_signals`) would be the alternative to a trigger, as 505 and 538 did for others; a trigger is used here because it
--     leaves the grants as the platform set them, and the three are named for that follow-up in the design record.
--
-- Idempotent (DROP TRIGGER IF EXISTS before each CREATE, CREATE OR REPLACE, REVOKE and GRANT are repeatable). Reversible: the
-- rollback drops the thirteen triggers and the new function and gives `clients` back the four verbs the migrations had granted it.
--
-- LOCKS. CREATE TRIGGER takes SHARE ROW EXCLUSIVE on its table and DROP TRIGGER ACCESS EXCLUSIVE, until the migration commits.
-- The runner sends one top-level statement per round trip, so the thirteen triggers are created inside ONE block (the review of
-- migration 539 ran the same kind of DDL as separate statements through a proxy adding a quarter of a second to each round
-- trip, an assumed figure and not the runner's, and a table was locked for about 15 seconds). REVOKE and GRANT lock the
-- catalogue row and not the table. A lock_timeout of 15 seconds, as migrations 536 to 539 set, makes a long-running transaction
-- that holds one of the tables fail the migration, to be re-run, instead of queueing every later request on it behind it.

SELECT set_config('lock_timeout', '15s', true);

-- ── 1. the function for the chart: any change of the client by a member who is not a Partner is refused ─────────────

CREATE OR REPLACE FUNCTION public.refuse_a_signed_in_member_changing_the_client_of_a_row()
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
       AND (to_jsonb(OLD) ->> v_column) IS DISTINCT FROM (to_jsonb(NEW) ->> v_column)
       AND COALESCE((SELECT public.get_my_role()), '') <> 'Partner'
    THEN
        RAISE EXCEPTION
            'Only a Partner can change the % of a % row: a row with none is shared by the whole firm and a row with one is that client''s. Nothing was changed.',
            v_column, TG_TABLE_NAME
            USING ERRCODE = '42501';
    END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION public.refuse_a_signed_in_member_changing_the_client_of_a_row() IS
    'POST-A-326. A signed-in session whose member is not a Partner may not change the named column (client_id) of a row of '
    'chart_of_accounts in any direction: a firm-level account is shared by every client of the firm. Migration 540.';

REVOKE ALL ON FUNCTION public.refuse_a_signed_in_member_changing_the_client_of_a_row() FROM PUBLIC, anon, authenticated;

-- ── 2. the thirteen triggers, in one block ───────────────────────────────────────────────────────────────────

DO $apply$
BEGIN
  DROP TRIGGER IF EXISTS an_activity_entry_keeps_its_client_unless_a_partner_clears_it ON public.activity_logs;
  CREATE TRIGGER an_activity_entry_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.activity_logs
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

  DROP TRIGGER IF EXISTS an_ai_evidence_row_keeps_its_client_unless_a_partner_clears_it ON public.ai_evidence;
  CREATE TRIGGER an_ai_evidence_row_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.ai_evidence
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

  DROP TRIGGER IF EXISTS an_ai_signal_keeps_its_client_unless_a_partner_clears_it ON public.ai_signals;
  CREATE TRIGGER an_ai_signal_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.ai_signals
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

  DROP TRIGGER IF EXISTS a_lifecycle_event_keeps_its_client_unless_a_partner_clears_it ON public.client_lifecycle_events;
  CREATE TRIGGER a_lifecycle_event_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.client_lifecycle_events
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

  DROP TRIGGER IF EXISTS an_article_keeps_its_client_unless_a_partner_clears_it ON public.knowledge_articles;
  CREATE TRIGGER an_article_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.knowledge_articles
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

  DROP TRIGGER IF EXISTS an_mca_filing_keeps_its_client_unless_a_partner_clears_it ON public.mca_filings;
  CREATE TRIGGER an_mca_filing_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.mca_filings
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

  DROP TRIGGER IF EXISTS a_proposal_keeps_its_client_unless_a_partner_clears_it ON public.proposals;
  CREATE TRIGGER a_proposal_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.proposals
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

  DROP TRIGGER IF EXISTS a_reminder_keeps_its_client_unless_a_partner_clears_it ON public.reminders;
  CREATE TRIGGER a_reminder_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.reminders
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

  DROP TRIGGER IF EXISTS a_scheduled_report_keeps_its_client_unless_a_partner_clears_it ON public.scheduled_reports;
  CREATE TRIGGER a_scheduled_report_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.scheduled_reports
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

  DROP TRIGGER IF EXISTS a_recurring_task_keeps_its_client_unless_a_partner_clears_it ON public.task_recurring_configs;
  CREATE TRIGGER a_recurring_task_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.task_recurring_configs
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

  DROP TRIGGER IF EXISTS a_time_entry_keeps_its_client_unless_a_partner_clears_it ON public.time_entries;
  CREATE TRIGGER a_time_entry_keeps_its_client_unless_a_partner_clears_it
    BEFORE UPDATE OF client_id ON public.time_entries
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('client_id');

  DROP TRIGGER IF EXISTS an_onboarding_task_keeps_its_workflow_unless_a_partner_clears ON public.onboarding_tasks;
  CREATE TRIGGER an_onboarding_task_keeps_its_workflow_unless_a_partner_clears
    BEFORE UPDATE OF workflow_id ON public.onboarding_tasks
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_clearing_the_parent_of_a_row('workflow_id');

  DROP TRIGGER IF EXISTS an_account_keeps_its_client_unless_a_partner_changes_it ON public.chart_of_accounts;
  CREATE TRIGGER an_account_keeps_its_client_unless_a_partner_changes_it
    BEFORE UPDATE OF client_id ON public.chart_of_accounts
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_member_changing_the_client_of_a_row('client_id');
END $apply$;

-- ── 3. nobody signed in can delete a client row ────────────────────────────────────────────────────────────────

REVOKE ALL ON public.clients FROM authenticated, anon, PUBLIC;
GRANT SELECT, INSERT, UPDATE ON public.clients TO authenticated;
-- the service role's own privileges are explicit, so that nothing above can have removed them through PUBLIC
GRANT SELECT, INSERT, UPDATE, DELETE ON public.clients TO service_role;

-- ── 4. the migration checks its own result ─────────────────────────────────────────────────────────────────────

DO $$
DECLARE
  v        record;
  v_left   text;
  v_priv   text;
BEGIN
  -- each trigger is the one written: its name, its table, BEFORE UPDATE OF exactly its column, its function and its argument
  FOR v IN SELECT * FROM (VALUES
      ('an_activity_entry_keeps_its_client_unless_a_partner_clears_it', 'activity_logs', 'client_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('an_ai_evidence_row_keeps_its_client_unless_a_partner_clears_it', 'ai_evidence', 'client_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('an_ai_signal_keeps_its_client_unless_a_partner_clears_it', 'ai_signals', 'client_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('a_lifecycle_event_keeps_its_client_unless_a_partner_clears_it', 'client_lifecycle_events', 'client_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('an_article_keeps_its_client_unless_a_partner_clears_it', 'knowledge_articles', 'client_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('an_mca_filing_keeps_its_client_unless_a_partner_clears_it', 'mca_filings', 'client_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('a_proposal_keeps_its_client_unless_a_partner_clears_it', 'proposals', 'client_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('a_reminder_keeps_its_client_unless_a_partner_clears_it', 'reminders', 'client_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('a_scheduled_report_keeps_its_client_unless_a_partner_clears_it', 'scheduled_reports', 'client_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('a_recurring_task_keeps_its_client_unless_a_partner_clears_it', 'task_recurring_configs', 'client_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('a_time_entry_keeps_its_client_unless_a_partner_clears_it', 'time_entries', 'client_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('an_onboarding_task_keeps_its_workflow_unless_a_partner_clears', 'onboarding_tasks', 'workflow_id', 'refuse_a_signed_in_member_clearing_the_parent_of_a_row'),
      ('an_account_keeps_its_client_unless_a_partner_changes_it', 'chart_of_accounts', 'client_id', 'refuse_a_signed_in_member_changing_the_client_of_a_row')
    ) AS x(trigger_name, tbl, col, fn)
  LOOP
    IF NOT EXISTS (
         SELECT 1
           FROM pg_trigger t
           JOIN pg_attribute a ON a.attrelid = t.tgrelid AND a.attname = v.col
          WHERE t.tgname = v.trigger_name
            AND t.tgrelid = ('public.' || v.tbl)::regclass
            AND t.tgfoid = ('public.' || v.fn || '()')::regprocedure
            AND NOT t.tgisinternal AND t.tgenabled = 'O'
            AND t.tgtype = 19                                  -- ROW, BEFORE, UPDATE
            AND t.tgattr::text = a.attnum::text                -- UPDATE OF exactly this column
            AND t.tgargs = convert_to(v.col, 'UTF8') || '\x00'::bytea) THEN
      RAISE EXCEPTION 'migration 540: trigger % on public.% is missing, disabled or not BEFORE UPDATE OF % calling %(%)',
        v.trigger_name, v.tbl, v.col, v.fn, v.col;
    END IF;
  END LOOP;

  -- what the signed-in, anonymous and PUBLIC grantees hold on clients, read from the ACL itself (so a verb this server version
  -- has and the one the CI database lacks, MAINTAIN, is seen too): the signed-in role keeps SELECT, INSERT, UPDATE and nothing else,
  -- and the anonymous role and PUBLIC hold nothing
  SELECT string_agg(DISTINCT CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END || ':' || a.privilege_type,
                    ', ' ORDER BY CASE WHEN a.grantee = 0 THEN 'PUBLIC' ELSE pg_get_userbyid(a.grantee) END || ':' || a.privilege_type)
    INTO v_left
    FROM pg_class c, aclexplode(COALESCE(c.relacl, acldefault('r', c.relowner))) a
   WHERE c.oid = 'public.clients'::regclass
     AND (a.grantee = 0
          OR a.grantee = (SELECT oid FROM pg_roles WHERE rolname = 'anon')
          OR (a.grantee = (SELECT oid FROM pg_roles WHERE rolname = 'authenticated')
              AND a.privilege_type NOT IN ('SELECT', 'INSERT', 'UPDATE')));
  IF v_left IS NOT NULL THEN
    RAISE EXCEPTION 'migration 540: public.clients still grants %', v_left;
  END IF;
  IF has_any_column_privilege('authenticated', 'public.clients', 'REFERENCES')
     OR has_any_column_privilege('anon', 'public.clients', 'SELECT, INSERT, UPDATE, REFERENCES') THEN
    RAISE EXCEPTION 'migration 540: a column privilege on public.clients is still held by the signed-in or anonymous role';
  END IF;
  FOREACH v_priv IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE'] LOOP
    IF NOT has_table_privilege('authenticated', 'public.clients', v_priv) THEN
      RAISE EXCEPTION 'migration 540: the signed-in role lost % on public.clients', v_priv;
    END IF;
  END LOOP;
  FOREACH v_priv IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
    IF NOT has_table_privilege('service_role', 'public.clients', v_priv) THEN
      RAISE EXCEPTION 'migration 540: the service role lost % on public.clients', v_priv;
    END IF;
  END LOOP;
  IF has_function_privilege('authenticated', 'public.refuse_a_signed_in_member_changing_the_client_of_a_row()', 'EXECUTE')
     OR has_function_privilege('anon', 'public.refuse_a_signed_in_member_changing_the_client_of_a_row()', 'EXECUTE') THEN
    RAISE EXCEPTION 'migration 540: a signed-in role can execute the account trigger function';
  END IF;
END $$;
