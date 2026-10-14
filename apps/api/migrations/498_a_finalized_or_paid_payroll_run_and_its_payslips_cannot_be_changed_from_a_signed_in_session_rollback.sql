-- Rollback of migration 498: removes the two triggers and their functions.
-- THIS RE-OPENS THE HOLE: a signed-in session with payroll write access can again change, delete or set to released a
-- finalized or paid payroll run, and change its payslips, straight over the database.
DROP TRIGGER IF EXISTS a_released_payroll_run_is_not_written_by_a_session ON public.payroll_runs;
DROP TRIGGER IF EXISTS a_released_runs_payslips_are_not_written_by_a_session ON public.payroll_slips;
DROP FUNCTION IF EXISTS public.refuse_a_signed_in_change_to_a_released_payroll_run();
DROP FUNCTION IF EXISTS public.refuse_a_signed_in_change_to_the_payslips_of_a_released_run();
