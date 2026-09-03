-- Migration 317: row-level security on the eight tables migration 062 skipped
--
-- WHAT IS WRONG
--
-- In a database built from these migrations, eight tables have RLS switched
-- OFF and grant the `authenticated` role table privileges:
--
--   credit_note_allocations   SELECT INSERT UPDATE DELETE
--   invoice_sequences         SELECT INSERT UPDATE
--   scheduler_runs            SELECT
--   task_dependencies         SELECT INSERT UPDATE DELETE
--   task_tags                 SELECT INSERT UPDATE DELETE
--   task_templates            SELECT
--   task_timeline_events      SELECT INSERT
--   user_capacity             SELECT INSERT UPDATE DELETE
--
-- RLS off plus a grant means Postgres enforces NOTHING. The frontend reads
-- roughly 83 tables directly through PostgREST with the caller's JWT, so on
-- such a database any authenticated user reads every firm's rows on all eight,
-- and writes five of them.
--
-- PRODUCTION IS NOT EXPOSED. It has RLS on for all eight, each with the
-- firm-scoped policy re-declared below, applied out-of-band through Supabase
-- Studio. The defect is in what the MIGRATIONS declare, so it lands on the CI
-- template and on any new environment — and it is exactly the drift the guard
-- comparison added in 316 exists to find.
--
-- HOW IT HAPPENED — the pattern, not the instance
--
-- Migration 062 enabled RLS on 28 tables, each guarded by
--   IF EXISTS (SELECT 1 FROM information_schema.tables WHERE table_name = t)
-- Twenty of those tables are created by migrations 063 to 069 — AFTER 062 runs.
-- On a replay the guard finds no table and skips it SILENTLY. Most were rescued
-- by a later migration that enabled RLS for its own reasons; six were not
-- (task_dependencies, task_tags, task_templates, task_timeline_events, and
-- scheduler_runs and user_capacity). invoice_sequences and
-- credit_note_allocations were never in 062's list at all.
--
-- And 062's safety argument was explicit about what would make this dangerous:
--
--     "These 28 tables are currently only reachable via the FastAPI backend
--      ... the `authenticated` role holds no table GRANT on any of them, so
--      PostgreSQL already denies direct access before RLS is evaluated.
--      ... should a future migration ever GRANT these tables to `authenticated`
--      (e.g. a blanket GRANT ON ALL TABLES), access stays correctly
--      firm-scoped instead of leaking."
--
-- That future migration arrived. 095_grant_reconciliation.sql and
-- 287_itc_reversal_register_grants.sql grant `authenticated` full DML on these
-- tables. The grant landed; the RLS it assumed never had.
--
-- tests/test_rls_covers_every_granted_table_pg.py now asserts the invariant
-- directly — no table the `authenticated` role can reach may have RLS off —
-- so the next silently-skipped guard fails a test instead of shipping.
--
-- WHAT THIS DOES
--
-- Enables RLS on the eight, and declares the policy production already has for
-- each, verbatim. In production both halves are no-ops. On every other database
-- they close the hole.
--
-- Each policy is created only if a policy of that name does not already exist,
-- so this never rewrites a policy in production — it only supplies a missing
-- one. ENABLE ROW LEVEL SECURITY is idempotent in Postgres.
--
-- Reproducing production exactly means keeping its roles: seven of the eight
-- policies are TO PUBLIC and one is TO authenticated. PUBLIC is the wider of
-- the two and converging the declarations onto `authenticated` is worth doing,
-- but it is a change to who may reach rows and belongs with the other thirty
-- policies in that state, not smuggled into a security fix.

DO $$
DECLARE
  spec record;
BEGIN
  FOR spec IN
    SELECT * FROM (VALUES
      -- table, policy name, roles, USING, WITH CHECK ('' = omit the clause)
      ('credit_note_allocations', 'firm_credit_note_allocations', 'authenticated',
         'firm_id = get_my_firm_id()', 'firm_id = get_my_firm_id()'),
      ('invoice_sequences', 'invoice_sequences_own_firm', 'public',
         'firm_id = get_my_firm_id()', ''),
      -- A sweep row is firm-wide: jobs/scheduler.py writes firm_id NULL for the
      -- daily run, so the policy has to admit it or the run vanishes from view.
      ('scheduler_runs', 'scheduler_runs_own_firm', 'public',
         '(firm_id = get_my_firm_id()) OR (firm_id IS NULL)', ''),
      -- No firm_id of its own; scoped through the task it depends on.
      ('task_dependencies', 'task_dependencies_via_task', 'public',
         'EXISTS (SELECT 1 FROM tasks t WHERE t.id = task_dependencies.task_id '
         'AND t.firm_id = get_my_firm_id())', ''),
      ('task_tags', 'task_tags_own_firm', 'public',
         'firm_id = get_my_firm_id()', ''),
      -- A NULL firm_id here is a template shipped with the product, visible to
      -- every firm; a non-NULL one belongs to the firm that wrote it.
      ('task_templates', 'task_templates_own_firm', 'public',
         '(firm_id IS NULL) OR (firm_id = get_my_firm_id())', ''),
      ('task_timeline_events', 'task_timeline_events_own_firm', 'public',
         'firm_id = get_my_firm_id()', ''),
      ('user_capacity', 'user_capacity_own_firm', 'public',
         'firm_id = get_my_firm_id()', '')
    ) AS v(tbl, pol, roles, using_expr, check_expr)
  LOOP
    IF to_regclass('public.' || spec.tbl) IS NULL THEN CONTINUE; END IF;

    EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', spec.tbl);

    IF EXISTS (SELECT 1 FROM pg_policy p
               WHERE p.polname = spec.pol
                 AND p.polrelid = ('public.' || spec.tbl)::regclass) THEN
      CONTINUE;
    END IF;

    EXECUTE format(
      'CREATE POLICY %I ON public.%I FOR ALL TO %s USING (%s)%s',
      spec.pol, spec.tbl, spec.roles, spec.using_expr,
      CASE WHEN spec.check_expr = '' THEN ''
           ELSE format(' WITH CHECK (%s)', spec.check_expr) END
    );
  END LOOP;
END $$;
