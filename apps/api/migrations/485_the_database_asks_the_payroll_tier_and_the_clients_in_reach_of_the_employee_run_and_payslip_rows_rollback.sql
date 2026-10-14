-- Rollback for migration 485: the 16 restrictive policies it added are dropped.
--
-- Rolling back RE-OPENS the holes 485 closes: an assigned Executive or Reviewer can read and write employees,
-- runs and payslips over PostgREST, and every member of the firm can read every client's attendance, leave and
-- tax declarations (and a Manager can write them for clients they are not assigned to). Nothing else changes;
-- no row is touched.

DROP POLICY IF EXISTS "payroll_employees_role_select" ON public.payroll_employees;
DROP POLICY IF EXISTS "payroll_employees_role_insert" ON public.payroll_employees;
DROP POLICY IF EXISTS "payroll_employees_role_update" ON public.payroll_employees;
DROP POLICY IF EXISTS "payroll_employees_role_delete" ON public.payroll_employees;

DROP POLICY IF EXISTS "payroll_runs_role_select" ON public.payroll_runs;
DROP POLICY IF EXISTS "payroll_runs_role_insert" ON public.payroll_runs;
DROP POLICY IF EXISTS "payroll_runs_role_update" ON public.payroll_runs;
DROP POLICY IF EXISTS "payroll_runs_role_delete" ON public.payroll_runs;

DROP POLICY IF EXISTS "payroll_slips_role_select" ON public.payroll_slips;
DROP POLICY IF EXISTS "payroll_slips_role_insert" ON public.payroll_slips;
DROP POLICY IF EXISTS "payroll_slips_role_update" ON public.payroll_slips;
DROP POLICY IF EXISTS "payroll_slips_role_delete" ON public.payroll_slips;

DROP POLICY IF EXISTS "attendance_employee_in_reach" ON public.attendance;
DROP POLICY IF EXISTS "leave_balances_employee_in_reach" ON public.leave_balances;
DROP POLICY IF EXISTS "payroll_it_declarations_employee_in_reach" ON public.payroll_it_declarations;
DROP POLICY IF EXISTS "payroll_it_declaration_items_declaration_in_reach" ON public.payroll_it_declaration_items;
