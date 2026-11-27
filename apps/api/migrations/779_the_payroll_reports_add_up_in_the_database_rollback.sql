-- Rollback of 779: drop the two payroll report functions. The service falls back to adding the payslips up itself.
DROP FUNCTION IF EXISTS public.payroll_run_summaries(uuid, uuid[]);
DROP FUNCTION IF EXISTS public.payroll_year_end_totals(uuid, uuid[]);
