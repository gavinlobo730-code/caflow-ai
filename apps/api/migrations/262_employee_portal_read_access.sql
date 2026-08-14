-- Migration 262: let a payroll employee read their own payroll records.
--
-- WHAT WAS BROKEN
--   app/portal/employee/page.tsx reads three tables — payroll_employees,
--   payroll_slips, leave_balances. Under RLS an employee could read NONE of
--   them, including their own payroll_employees row. Proven against a real
--   Postgres with every migration applied: an authenticated session whose
--   auth.uid() matches payroll_employees.auth_user_id counted 0 rows on all
--   three, plus 0 on payroll_runs and the salary_slips view.
--
--   Migration 031 added `employee_sees_own_record` (PERMISSIVE, SELECT,
--   auth_user_id = auth.uid()) and that policy is correct — but it has never
--   had any effect, because a RESTRICTIVE policy added later ANDs with it:
--
--     payroll_employees_assignment_scope  RESTRICTIVE  ALL
--       USING can_access_client(client_id::text)
--
--   can_access_client() is
--       p_client_id IS NULL  OR get_my_role() = 'Partner'  OR EXISTS(...users...)
--   and every branch collapses for a portal employee: client_id is NOT NULL,
--   get_my_role() reads `users` and a portal employee has no `users` row so it
--   returns NULL ('NULL = Partner' is NULL, not false), and the EXISTS is
--   false. false OR NULL OR false = NULL, and RLS treats NULL as deny.
--
--   That is the whole reason the portal is blank. It is not a payroll_slips
--   problem — payroll_slips has no RESTRICTIVE policy at all; it is missing a
--   PERMISSIVE one. Both halves are fixed here.
--
-- THE SHAPE OF THE FIX
--   A portal employee is not staff. The assignment-scope policies exist to
--   stop a staff member reading clients they are not assigned to, and that
--   question simply does not apply to someone reading their own payslip. So
--   the exception is written into the assignment-scope policies themselves —
--   RESTRICTIVE policies AND together, so there is no way to add an exception
--   from outside one.
--
--   The exception is READ ONLY: the FOR ALL policies are split per command and
--   only the SELECT arm carries the employee branch. INSERT/UPDATE/DELETE keep
--   the original can_access_client() rule verbatim. Same mechanic as 260/261.
--
--   Be precise about what that split buys, because it is easy to overstate.
--   TODAY an employee already cannot write, whatever the RESTRICTIVE policies
--   say, because no PERMISSIVE policy admits them for a write: own_firm is
--   gated on get_my_firm_id() (NULL for an employee) and employee_sees_own_record
--   is SELECT-only. Widening the FOR ALL form would therefore have been
--   indistinguishable in behaviour — a mutation test confirmed it: putting the
--   employee branch on the UPDATE policy changes nothing observable.
--
--   The split is defence in depth against the NEXT change. The moment someone
--   adds a permissive write policy for employees — "let them edit their own
--   bank details" is the obvious one — a widened FOR ALL restrictive policy
--   would silently hand them their salary fields too. Keeping the employee
--   branch on SELECT alone means that future policy grants exactly what it
--   says and nothing else. Because this has no behavioural signature today,
--   it is pinned structurally instead:
--   test_262_employee_portal_rls_pg.py::test_no_write_policy_admits_an_employee.
--
-- WHY THE HELPER FUNCTIONS ARE SECURITY DEFINER
--   A policy on payroll_employees that sub-selects payroll_employees, or one
--   on payroll_runs that sub-selects payroll_slips (whose own policy reads
--   payroll_runs), recurses — Postgres raises "infinite recursion detected in
--   policy for relation ...". SECURITY DEFINER runs as the table owner, who is
--   exempt from RLS (none of these tables use FORCE ROW LEVEL SECURITY), which
--   breaks the cycle. This is the same device can_access_client() already uses.
--
-- WHY portal_enabled IS PART OF THE TEST
--   payroll_employees.portal_enabled is the CA's switch for "this person may
--   use the portal", and the page already filters on it. Gating the DATA on it
--   too means switching it off actually withdraws access instead of merely
--   hiding a link. employee_sees_own_record is tightened to match, so the flag
--   means one thing in both places rather than two.
--
--   NOTE FOR WHOEVER WIRES UP PROVISIONING: nothing in the codebase currently
--   writes payroll_employees.auth_user_id or .portal_enabled. This migration
--   makes the portal readable once an employee is linked to an auth identity;
--   it does not create that link. Until something sets those two columns the
--   portal stays empty — correctly so, and now for a reason a CA can act on
--   rather than a policy quirk.

-- RE-RUNNABLE, AND ATOMIC. Both matter, for reasons that only show up outside
-- a clean install.
--
--   * Every CREATE POLICY here is preceded by DROP POLICY IF EXISTS. The
--     migration runner skips files already recorded in public.schema_migrations,
--     so a second run normally never happens — but it does happen when a
--     migration is applied out of band (e.g. through the Supabase dashboard or
--     MCP, which record into supabase_migrations.schema_migrations, a DIFFERENT
--     table). Without the guards the re-run dies on "policy ... already exists".
--     The CI migration job cannot catch this: it applies each file exactly once
--     to a throwaway database.
--
--   * scripts/db/apply_migrations.py invokes `psql -f` WITHOUT
--     --single-transaction, so without the BEGIN/COMMIT below each statement
--     would autocommit independently. A failure between the DROP and the CREATE
--     of a RESTRICTIVE policy would then leave that policy dropped and not
--     recreated — and dropping a RESTRICTIVE policy WIDENS access. Wrapping the
--     file makes that impossible: it either fully applies or does nothing.

BEGIN;

-- ─── 1. One auth identity, one employee record ───────────────────────────────
-- Every policy below scopes by auth_user_id. Without uniqueness, two employee
-- rows sharing an auth_user_id would each see the other's payslips — the exact
-- disclosure these policies exist to prevent. Partial, so the many employees
-- with no portal login (auth_user_id IS NULL) are unaffected.
CREATE UNIQUE INDEX IF NOT EXISTS payroll_employees_auth_user_id_key
  ON public.payroll_employees (auth_user_id)
  WHERE auth_user_id IS NOT NULL;

-- ─── 2. Helpers ──────────────────────────────────────────────────────────────
-- The employee record(s) belonging to the caller. Returns nothing for staff,
-- for anon, and for an employee whose portal has been switched off.
CREATE OR REPLACE FUNCTION public.my_employee_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT e.id
  FROM public.payroll_employees e
  WHERE e.auth_user_id = auth.uid()
    AND e.portal_enabled IS TRUE
$$;

-- The payroll runs that produced one of the caller's own payslips. Needed
-- because the portal reads payroll_slips with a payroll_runs!inner(month)
-- embed for the period, and PostgREST's inner join drops the slip unless the
-- parent run is visible too — as does the salary_slips view, which JOINs
-- payroll_runs to derive month/year.
CREATE OR REPLACE FUNCTION public.my_payroll_run_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT DISTINCT s.run_id
  FROM public.payroll_slips s
  WHERE s.employee_id IN (SELECT public.my_employee_ids())
$$;

-- Same posture as get_my_firm_id() in migration 016: usable by a logged-in
-- session, not reachable from the anon role.
REVOKE EXECUTE ON FUNCTION public.my_employee_ids()    FROM PUBLIC, anon;
REVOKE EXECUTE ON FUNCTION public.my_payroll_run_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_employee_ids()    TO authenticated;
GRANT  EXECUTE ON FUNCTION public.my_payroll_run_ids() TO authenticated;

-- ─── 3. payroll_employees — unblock the employee's own row ───────────────────
-- Replaces one FOR ALL restrictive policy with four per-command ones. Only the
-- SELECT arm gains the employee branch; the other three are the original rule,
-- unchanged, so staff scoping is exactly as it was and no write path widens.
DROP POLICY IF EXISTS "payroll_employees_assignment_scope" ON public.payroll_employees;

DROP POLICY IF EXISTS "payroll_employees_assignment_scope_select" ON public.payroll_employees;
CREATE POLICY "payroll_employees_assignment_scope_select" ON public.payroll_employees
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client(client_id::text)
    OR id IN (SELECT public.my_employee_ids())
  );

DROP POLICY IF EXISTS "payroll_employees_assignment_scope_insert" ON public.payroll_employees;
CREATE POLICY "payroll_employees_assignment_scope_insert" ON public.payroll_employees
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "payroll_employees_assignment_scope_update" ON public.payroll_employees;
CREATE POLICY "payroll_employees_assignment_scope_update" ON public.payroll_employees
  AS RESTRICTIVE FOR UPDATE
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "payroll_employees_assignment_scope_delete" ON public.payroll_employees;
CREATE POLICY "payroll_employees_assignment_scope_delete" ON public.payroll_employees
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client(client_id::text));

-- Tightened to agree with my_employee_ids(): the portal switch now governs the
-- data, not just the page. Was: auth_user_id = auth.uid().
DROP POLICY IF EXISTS "employee_sees_own_record" ON public.payroll_employees;
CREATE POLICY "employee_sees_own_record" ON public.payroll_employees
  FOR SELECT TO authenticated
  USING (id IN (SELECT public.my_employee_ids()));

-- ─── 4. payroll_runs — the parent row behind the period ──────────────────────
-- Same split, same reason. The employee branch admits only runs that produced
-- one of their own payslips, so a run they have no slip in stays invisible.
DROP POLICY IF EXISTS "payroll_runs_assignment_scope" ON public.payroll_runs;

DROP POLICY IF EXISTS "payroll_runs_assignment_scope_select" ON public.payroll_runs;
CREATE POLICY "payroll_runs_assignment_scope_select" ON public.payroll_runs
  AS RESTRICTIVE FOR SELECT
  USING (
    public.can_access_client(client_id::text)
    OR id IN (SELECT public.my_payroll_run_ids())
  );

DROP POLICY IF EXISTS "payroll_runs_assignment_scope_insert" ON public.payroll_runs;
CREATE POLICY "payroll_runs_assignment_scope_insert" ON public.payroll_runs
  AS RESTRICTIVE FOR INSERT
  WITH CHECK (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "payroll_runs_assignment_scope_update" ON public.payroll_runs;
CREATE POLICY "payroll_runs_assignment_scope_update" ON public.payroll_runs
  AS RESTRICTIVE FOR UPDATE
  USING (public.can_access_client(client_id::text))
  WITH CHECK (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "payroll_runs_assignment_scope_delete" ON public.payroll_runs;
CREATE POLICY "payroll_runs_assignment_scope_delete" ON public.payroll_runs
  AS RESTRICTIVE FOR DELETE
  USING (public.can_access_client(client_id::text));

DROP POLICY IF EXISTS "employee_reads_own_payroll_runs" ON public.payroll_runs;
CREATE POLICY "employee_reads_own_payroll_runs" ON public.payroll_runs
  FOR SELECT TO authenticated
  USING (id IN (SELECT public.my_payroll_run_ids()));

-- ─── 5. payroll_slips — the payslips themselves ──────────────────────────────
-- No RESTRICTIVE policy here to split; the gap was a missing PERMISSIVE one.
-- PERMISSIVE policies OR together, so this sits alongside payroll_slips_own_firm
-- (staff, by firm) without touching it.
DROP POLICY IF EXISTS "employee_reads_own_payslips" ON public.payroll_slips;
CREATE POLICY "employee_reads_own_payslips" ON public.payroll_slips
  FOR SELECT TO authenticated
  USING (employee_id IN (SELECT public.my_employee_ids()));

-- ─── 6. leave_balances — the portal's leave tab ──────────────────────────────
-- Its RESTRICTIVE policies from migration 261 are INSERT/UPDATE/DELETE only, so
-- SELECT needs no split — just the missing PERMISSIVE read.
DROP POLICY IF EXISTS "employee_reads_own_leave_balances" ON public.leave_balances;
CREATE POLICY "employee_reads_own_leave_balances" ON public.leave_balances
  FOR SELECT TO authenticated
  USING (employee_id IN (SELECT public.my_employee_ids()));

COMMIT;
