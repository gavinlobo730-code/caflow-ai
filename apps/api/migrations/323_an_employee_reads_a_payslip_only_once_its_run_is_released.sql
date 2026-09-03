-- Migration 323: an employee may read a payslip only once its run is released.
--
-- WHAT WAS BROKEN
--   Migration 262 gave a portal employee read access to their own payslip and
--   to the run behind it, scoped by IDENTITY and by nothing else:
--
--     employee_reads_own_payslips     USING (employee_id IN (SELECT my_employee_ids()))
--     employee_reads_own_payroll_runs USING (id IN (SELECT my_payroll_run_ids()))
--
--   payroll_runs.status is NOT NULL DEFAULT 'draft' over the vocabulary
--   draft / review / finalized / paid (migrations 014, 054, 093, 225). Neither
--   policy looks at it. So the moment a CA generates a run — POST /api/payroll/runs
--   writes status 'draft' — every portal-linked employee of that client could
--   read their own UNAPPROVED payslip: before the reviewer, before the client
--   employer signed it off, before a rupee was posted.
--
--   The rest of the codebase already draws this line and only the database did
--   not. The PF ECR and the ESIC return both refuse a run that is not finalised,
--   in those words — "a draft run's figures can still change" — Form 16 and the
--   24Q filter their source runs the same way, and services/tds_return_service.py
--   names the released pair _PAYROLL_POSTED = ("finalized", "paid").
--
--   Not exploited: production holds no payroll_employees row with auth_user_id
--   or portal_enabled set, so nobody can be logged in as an employee yet. It
--   goes live with the first invite migration 264 shipped.
--
-- WHY THE POLICY AND NOT THE PAGE
--   app/portal/employee/page.tsx selects payroll_slips directly through
--   PostgREST, as ~83 tables are read on that path. CLAUDE.md is explicit that
--   rbac() never runs there and RLS is the only check, so a filter added to the
--   query would be a suggestion, not a control.
--
-- WHY BOTH OBJECTS, NOT JUST THE FUNCTION
--   Tightening my_payroll_run_ids() alone fixes payroll_runs, and the portal's
--   payroll_runs!inner(month) embed would then drop a draft slip as a side
--   effect of the inner join. That is a property of the CALLER's query shape,
--   not of the policy: a plain select on payroll_slips would still return the
--   draft. So the slip policy carries the predicate itself.
--
--   Result: two independent barriers, and neither relies on how the row is
--   asked for.

-- ─── 1. the run set an employee may see ──────────────────────────────────────
-- Was "the runs that produced a slip of mine" — a question about ownership.
-- The missing half is release.
CREATE OR REPLACE FUNCTION public.my_payroll_run_ids()
RETURNS SETOF uuid
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT DISTINCT s.run_id
  FROM public.payroll_slips s
  JOIN public.payroll_runs r ON r.id = s.run_id
  WHERE s.employee_id IN (SELECT public.my_employee_ids())
    AND r.status IN ('finalized', 'paid')
$$;

-- Unchanged from 262, restated because CREATE OR REPLACE does not carry grants
-- forward on a signature change and the drift check reads them.
REVOKE EXECUTE ON FUNCTION public.my_payroll_run_ids() FROM PUBLIC, anon;
GRANT  EXECUTE ON FUNCTION public.my_payroll_run_ids() TO authenticated;

-- ─── 2. the payslip itself ───────────────────────────────────────────────────
DROP POLICY IF EXISTS "employee_reads_own_payslips" ON public.payroll_slips;
CREATE POLICY "employee_reads_own_payslips" ON public.payroll_slips
  FOR SELECT TO authenticated
  USING (
    employee_id IN (SELECT public.my_employee_ids())
    AND run_id IN (SELECT public.my_payroll_run_ids())
  );
