-- Migration 485 — the database asks the payroll tier, and the clients in reach, of the employee, run and payslip rows
-- (security_privacy-34, found by the role-by-table access matrix; ledger POST-B-004, POST-B-012 and the payroll
-- part of POST-B-015).
--
-- THE HOLES (each reproduced by tests/test_rls_role_by_table_matrix_pg.py before this migration)
--
--   1. `payroll_employees`, `payroll_runs` and `payroll_slips` carry a firm policy and an assignment scope (084)
--      and NO role tier. The API reserves payroll to Manager and above (`payroll:read` and `payroll:write`,
--      core/permissions.py: "salary data is sensitive"), but an Executive or a Reviewer assigned to a payroll
--      client reached the same rows straight over PostgREST with their own JWT: every employee's PAN, UAN, bank
--      account and salary, every run's totals and every payslip, and could write them.
--
--   2. `attendance`, `leave_balances`, `payroll_it_declarations` and `payroll_it_declaration_items` have no
--      `client_id`, so 084's assignment scope never reached them. Their only SELECT rule was the firm, so every
--      member read every client's attendance, leave and tax declarations, and a Manager read and wrote the
--      rows of clients they were not assigned to (and deleted attendance and leave rows).
--
-- WHAT THIS DOES
--   All new policies are RESTRICTIVE, so they AND with the existing firm-isolation, assignment-scope and
--   employee-own-record rules and can only narrow, never widen. Role is asked through
--   `my_permission(resource, action, minimum_role)`, the function the route's `rbac()` resolves through, so a
--   per-person grant or denial in the access grid (migrations 403/415) is honoured in both places.
--
--   payroll_employees, payroll_runs
--       SELECT          my_permission('payroll', 'read', 'Manager')
--                       OR the row is the caller's own (my_employee_ids() / my_payroll_run_ids(), 262)
--       INSERT, UPDATE, DELETE   my_permission('payroll', 'write', 'Manager')
--   payroll_slips
--       SELECT          my_permission('payroll', 'read', 'Manager')
--                       OR (employee is the caller's own AND the run is one they may see: 323, a payslip is
--                       readable by its employee only once the run is released)
--       INSERT, UPDATE, DELETE   my_permission('payroll', 'write', 'Manager')
--   attendance, leave_balances, payroll_it_declarations
--       ALL             the employee is one the caller can read from `payroll_employees`
--   payroll_it_declaration_items
--       ALL             the declaration is one the caller can read from `payroll_it_declarations`
--
--   The four child tables are scoped through their PARENT rather than through a copied client_id. A policy
--   expression's subquery runs under the caller's own row security, so `employee_id IN (SELECT id FROM
--   payroll_employees)` means exactly "an employee row this person is allowed to see": the payroll tier, the
--   assignment scope, the internal practice client's Partner-only rule and an employee's own record all come
--   with it, and there is no second copy of any of them to drift. (The same shape as 483's year-end notes.)
--   The existing role policies on those tables (261/296: Manager to write, an employee their own unverified
--   declaration) are untouched and still apply.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * The employee portal. An employee still reads their own employee row, their own released payslips and
--     their own declarations, and writes their own unverified declaration; the matrix proves it cell by cell.
--   * Partner-only FINALISE and the "a released run cannot be changed" rule are still the API's alone. A trigger
--     for the second is the remaining half of POST-B-004 and is not here.
--   * THE OTHER PAYROLL TABLES, WHICH ARE STILL READABLE BY EVERY MEMBER OF THE FIRM, and the name of this
--     migration is chosen so that it does not claim otherwise. These carry a firm-only read rule (and a role tier on
--     their writes) and are NOT covered here: payroll_salary_revisions, salary_structures, payroll_perquisites,
--     payroll_loans, payroll_loan_recoveries, payroll_settlements, payroll_settlement_components,
--     payroll_one_time_earnings, bonus_disqualifications, and the run-keyed payroll_run_transitions,
--     statutory_remittances, epfo_ecr_filings and reconciliation_findings. An Executive, a Reviewer or a Manager the
--     Partner has blocked from payroll can still select a basic salary, a loan or a settlement from them over
--     PostgREST. They are not in the access matrix and the browser does not reach them, which is why they were not
--     measured here, and it is NOT a reason to leave them: the threat the matrix models is a direct call with the
--     caller's own JWT. They are the next ledger line (the same parent-employee / parent-run scoping, after a check of
--     every reader under a caller's JWT, as was done for the seven tables above).
--   * No function, grant, table or row changes. No backfill.
--
-- WHO NOTICES, AND WHAT THE API DID ABOUT IT (same commit)
--   Under USE_USER_JWT the API runs as the caller, so this binds the API path too. Three doors read payroll data
--   under the caller's own sign-in for people who do not hold `payroll:read`, and would now have answered EMPTY,
--   which is worse than a refusal: Form 24Q built from the books (`POST /api/tds/24q/from-books`, `tds:compute` is
--   Executive), the 24Q rows of the TDS filing walk-through, and the bank-account delete check (`payroll_runs`
--   paid from the account). The first two now require `payroll:read` and say so; the third reads the one fact it
--   needs (is there a payroll run paid from this account) through the service client, after the caller's access to
--   the client is checked, because an Executive may delete a mistaken bank account and must not be told it is
--   deletable by a probe that could not see the answer.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, and the closing check fails the migration (and so the
-- deploy) if any policy is missing. Reversible:
-- 485_the_database_asks_the_payroll_tier_and_the_clients_in_reach_of_the_employee_run_and_payslip_rows_rollback.sql
-- drops them again, which RE-OPENS the holes.

-- ── payroll_employees ────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "payroll_employees_role_select" ON public.payroll_employees;
CREATE POLICY "payroll_employees_role_select" ON public.payroll_employees
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.my_permission('payroll', 'read', 'Manager')
         OR id IN (SELECT public.my_employee_ids()));

DROP POLICY IF EXISTS "payroll_employees_role_insert" ON public.payroll_employees;
CREATE POLICY "payroll_employees_role_insert" ON public.payroll_employees
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_employees_role_update" ON public.payroll_employees;
CREATE POLICY "payroll_employees_role_update" ON public.payroll_employees
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_employees_role_delete" ON public.payroll_employees;
CREATE POLICY "payroll_employees_role_delete" ON public.payroll_employees
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'));

-- ── payroll_runs ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "payroll_runs_role_select" ON public.payroll_runs;
CREATE POLICY "payroll_runs_role_select" ON public.payroll_runs
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.my_permission('payroll', 'read', 'Manager')
         OR id IN (SELECT public.my_payroll_run_ids()));

DROP POLICY IF EXISTS "payroll_runs_role_insert" ON public.payroll_runs;
CREATE POLICY "payroll_runs_role_insert" ON public.payroll_runs
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_runs_role_update" ON public.payroll_runs;
CREATE POLICY "payroll_runs_role_update" ON public.payroll_runs
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_runs_role_delete" ON public.payroll_runs;
CREATE POLICY "payroll_runs_role_delete" ON public.payroll_runs
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'));

-- ── payroll_slips ────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "payroll_slips_role_select" ON public.payroll_slips;
CREATE POLICY "payroll_slips_role_select" ON public.payroll_slips
  AS RESTRICTIVE FOR SELECT TO authenticated
  USING (public.my_permission('payroll', 'read', 'Manager')
         OR (employee_id IN (SELECT public.my_employee_ids())
             AND run_id IN (SELECT public.my_payroll_run_ids())));

DROP POLICY IF EXISTS "payroll_slips_role_insert" ON public.payroll_slips;
CREATE POLICY "payroll_slips_role_insert" ON public.payroll_slips
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_slips_role_update" ON public.payroll_slips;
CREATE POLICY "payroll_slips_role_update" ON public.payroll_slips
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'))
  WITH CHECK (public.my_permission('payroll', 'write', 'Manager'));

DROP POLICY IF EXISTS "payroll_slips_role_delete" ON public.payroll_slips;
CREATE POLICY "payroll_slips_role_delete" ON public.payroll_slips
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('payroll', 'write', 'Manager'));

-- ── the children that have no client_id: scoped through their parent ────────
DROP POLICY IF EXISTS "attendance_employee_in_reach" ON public.attendance;
CREATE POLICY "attendance_employee_in_reach" ON public.attendance
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (employee_id IN (SELECT e.id FROM public.payroll_employees e))
  WITH CHECK (employee_id IN (SELECT e.id FROM public.payroll_employees e));

DROP POLICY IF EXISTS "leave_balances_employee_in_reach" ON public.leave_balances;
CREATE POLICY "leave_balances_employee_in_reach" ON public.leave_balances
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (employee_id IN (SELECT e.id FROM public.payroll_employees e))
  WITH CHECK (employee_id IN (SELECT e.id FROM public.payroll_employees e));

DROP POLICY IF EXISTS "payroll_it_declarations_employee_in_reach" ON public.payroll_it_declarations;
CREATE POLICY "payroll_it_declarations_employee_in_reach" ON public.payroll_it_declarations
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (employee_id IN (SELECT e.id FROM public.payroll_employees e))
  WITH CHECK (employee_id IN (SELECT e.id FROM public.payroll_employees e));

DROP POLICY IF EXISTS "payroll_it_declaration_items_declaration_in_reach" ON public.payroll_it_declaration_items;
CREATE POLICY "payroll_it_declaration_items_declaration_in_reach" ON public.payroll_it_declaration_items
  AS RESTRICTIVE FOR ALL TO authenticated
  USING (declaration_id IN (SELECT d.id FROM public.payroll_it_declarations d))
  WITH CHECK (declaration_id IN (SELECT d.id FROM public.payroll_it_declarations d));

-- ── the closing check: all 16 policies exist and every one is RESTRICTIVE ─────
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_policies
   WHERE schemaname = 'public'
     AND permissive = 'RESTRICTIVE'
     AND policyname IN (
       'payroll_employees_role_select', 'payroll_employees_role_insert',
       'payroll_employees_role_update', 'payroll_employees_role_delete',
       'payroll_runs_role_select', 'payroll_runs_role_insert',
       'payroll_runs_role_update', 'payroll_runs_role_delete',
       'payroll_slips_role_select', 'payroll_slips_role_insert',
       'payroll_slips_role_update', 'payroll_slips_role_delete',
       'attendance_employee_in_reach', 'leave_balances_employee_in_reach',
       'payroll_it_declarations_employee_in_reach', 'payroll_it_declaration_items_declaration_in_reach');
  IF n <> 16 THEN
    RAISE EXCEPTION 'migration 485: expected 16 restrictive policies, found %', n;
  END IF;
END $$;
