-- Migration 503: a signed-in member writes only the workflow templates (and their steps) of its OWN firm, and never a system one
-- (ledger POST-A-249, found by the independent review of POST-A-047).
--
-- WHAT WAS WRONG
--   Migration 157 gave `workflow_templates` the policy "firm_isolation": PERMISSIVE, FOR ALL, `USING (firm_id = get_my_firm_id()
--   OR is_system = true)` and NO `WITH CHECK`. For INSERT and UPDATE Postgres then uses the USING expression as the check, so
--   the second half admits any row that SAYS it is a system template. `authenticated` holds INSERT, UPDATE and DELETE on the
--   table (read from production on 17-10-2026, with the policy exactly so). A signed-in member of ANY firm could therefore
--   * insert a template with `is_system = true`, under any `firm_id` including another firm's;
--   * update or delete any existing system template, which every firm reads;
--   and `workflow_repository.get_analytics` / `list_templates` read `firm_id = mine OR is_system = true`, so the planted row
--   appeared in every other firm's template list, in its workflow analytics, and in the prompt the copilot's workflow report
--   builds from them. `workflow_steps` had the same shape through its template ("firm_isolation_via_template", no
--   WITH CHECK), so the steps of a system template were writable by anyone. The second policy on the table,
--   `workflow_templates_firm_isolation` (migration 062, FOR ALL TO authenticated, `firm_id = get_my_firm_id()` both ways),
--   is correct for the firm's own rows but does not stop an own-firm row from being written WITH `is_system = true`, which
--   the shared read then publishes to everyone.
--   Production, read on 17-10-2026, held no workflow template at all, and no code path writes `is_system = true` as a
--   signed-in session (the repository's create paths write false; the rows with true are mock data), so nothing that works
--   today moves.
--
-- WHAT THIS DOES
--   * drops "firm_isolation" on `workflow_templates` and "firm_isolation_via_template" on `workflow_steps`;
--   * READ: a signed-in member reads their own firm's templates (still through `workflow_templates_firm_isolation`) and any
--     system template (new SELECT-only policy); the steps of either, through the template;
--   * WRITE: three RESTRICTIVE policies on `workflow_templates` (INSERT, UPDATE, DELETE) require `is_system = false`, so
--     whatever permissive policy admits a row, a system row is never inserted, updated, deleted, or created by an update;
--     the permissive `workflow_templates_firm_isolation` still limits writes to the member's own firm. On `workflow_steps`
--     the INSERT, UPDATE and DELETE policies require the template to be the member's own firm's and not a system one.
--   * a closing check that fails the migration (and so the deploy) if a permissive policy that admits `is_system = true`
--     remains for any command that writes.
--   Not touched: `service_role` (the API's privileged client and the seed path) bypasses row security; the grants (POST-A-248
--   is the ledger line for taking them away after the repository stops writing as the caller); every other workflow table.
--
-- Idempotent. Reversible: 503_..._rollback.sql restores the two policies exactly as production holds them, which RE-OPENS the hole.

-- ── workflow_templates ──────────────────────────────────────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "firm_isolation" ON public.workflow_templates;

DROP POLICY IF EXISTS "workflow_templates_read_system" ON public.workflow_templates;
CREATE POLICY "workflow_templates_read_system" ON public.workflow_templates
    AS PERMISSIVE FOR SELECT TO authenticated
    USING (is_system = true);

DROP POLICY IF EXISTS "workflow_templates_never_a_system_row_insert" ON public.workflow_templates;
CREATE POLICY "workflow_templates_never_a_system_row_insert" ON public.workflow_templates
    AS RESTRICTIVE FOR INSERT TO authenticated
    WITH CHECK (is_system = false);

DROP POLICY IF EXISTS "workflow_templates_never_a_system_row_update" ON public.workflow_templates;
CREATE POLICY "workflow_templates_never_a_system_row_update" ON public.workflow_templates
    AS RESTRICTIVE FOR UPDATE TO authenticated
    USING (is_system = false)
    WITH CHECK (is_system = false);

DROP POLICY IF EXISTS "workflow_templates_never_a_system_row_delete" ON public.workflow_templates;
CREATE POLICY "workflow_templates_never_a_system_row_delete" ON public.workflow_templates
    AS RESTRICTIVE FOR DELETE TO authenticated
    USING (is_system = false);

-- ── workflow_steps (no firm_id: scoped through the template) ────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "firm_isolation_via_template" ON public.workflow_steps;

DROP POLICY IF EXISTS "workflow_steps_read" ON public.workflow_steps;
CREATE POLICY "workflow_steps_read" ON public.workflow_steps
    AS PERMISSIVE FOR SELECT TO authenticated
    USING (EXISTS (
        SELECT 1 FROM public.workflow_templates t
         WHERE t.id = workflow_steps.template_id
           AND (t.firm_id = get_my_firm_id() OR t.is_system = true)));

DROP POLICY IF EXISTS "workflow_steps_insert_own_firm" ON public.workflow_steps;
CREATE POLICY "workflow_steps_insert_own_firm" ON public.workflow_steps
    AS PERMISSIVE FOR INSERT TO authenticated
    WITH CHECK (EXISTS (
        SELECT 1 FROM public.workflow_templates t
         WHERE t.id = workflow_steps.template_id
           AND t.firm_id = get_my_firm_id() AND t.is_system = false));

DROP POLICY IF EXISTS "workflow_steps_update_own_firm" ON public.workflow_steps;
CREATE POLICY "workflow_steps_update_own_firm" ON public.workflow_steps
    AS PERMISSIVE FOR UPDATE TO authenticated
    USING (EXISTS (
        SELECT 1 FROM public.workflow_templates t
         WHERE t.id = workflow_steps.template_id
           AND t.firm_id = get_my_firm_id() AND t.is_system = false))
    WITH CHECK (EXISTS (
        SELECT 1 FROM public.workflow_templates t
         WHERE t.id = workflow_steps.template_id
           AND t.firm_id = get_my_firm_id() AND t.is_system = false));

DROP POLICY IF EXISTS "workflow_steps_delete_own_firm" ON public.workflow_steps;
CREATE POLICY "workflow_steps_delete_own_firm" ON public.workflow_steps
    AS PERMISSIVE FOR DELETE TO authenticated
    USING (EXISTS (
        SELECT 1 FROM public.workflow_templates t
         WHERE t.id = workflow_steps.template_id
           AND t.firm_id = get_my_firm_id() AND t.is_system = false));

-- ── the closing check ───────────────────────────────────────────────────────────────────────────────────────────────
-- No permissive policy on either table may admit `is_system = true` for a command that writes (INSERT '(a)', UPDATE '(w)',
-- DELETE '(d)', or ALL '(*)'), and the three restrictive policies must be there.
DO $$
DECLARE
  open_door text;
  restrictive int;
BEGIN
  SELECT string_agg(c.relname || '.' || p.polname, ', ' ORDER BY c.relname, p.polname) INTO open_door
    FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid
   WHERE c.relnamespace = 'public'::regnamespace AND c.relname IN ('workflow_templates', 'workflow_steps')
     AND p.polpermissive AND p.polcmd IN ('*', 'a', 'w', 'd')
     AND (coalesce(pg_get_expr(p.polqual, p.polrelid), '') LIKE '%is_system = true%'
          OR coalesce(pg_get_expr(p.polwithcheck, p.polrelid), '') LIKE '%is_system = true%');
  IF open_door IS NOT NULL THEN
    RAISE EXCEPTION 'migration 503: a permissive policy still admits a system workflow row to a write: %', open_door;
  END IF;

  SELECT count(*) INTO restrictive
    FROM pg_policy p JOIN pg_class c ON c.oid = p.polrelid
   WHERE c.relnamespace = 'public'::regnamespace AND c.relname = 'workflow_templates' AND NOT p.polpermissive
     AND p.polcmd IN ('a', 'w', 'd');
  IF restrictive <> 3 THEN
    RAISE EXCEPTION 'migration 503: expected three restrictive write policies on workflow_templates, found %', restrictive;
  END IF;
END $$;
