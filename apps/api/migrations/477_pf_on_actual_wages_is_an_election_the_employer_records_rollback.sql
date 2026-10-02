-- Rollback for 477. DISCARDS every recorded PF election and every slip's record of
-- whether its contribution was on actual wages.
--
-- Roll the code back with this file. With the columns gone `_compute_slip` still
-- writes `pf_on_actual_wages` on every slip it inserts, so a payroll run would fail
-- until the code is rolled back too; and a month already finalised on actual wages
-- keeps the contributions its slips hold while losing the flag the ECR reads, so its
-- ECR would declare the EPF wage at the ceiling against a contribution computed on
-- the whole wage. Do not roll back while a finalised run carries an election.

BEGIN;

ALTER TABLE public.payroll_employees
  DROP CONSTRAINT IF EXISTS payroll_employees_pf_election_date_plausible,
  DROP CONSTRAINT IF EXISTS payroll_employees_pf_election_reference_shape,
  DROP CONSTRAINT IF EXISTS payroll_employees_pf_election_detail_needs_election,
  DROP CONSTRAINT IF EXISTS payroll_employees_pf_election_needs_pf;

ALTER TABLE public.payroll_slips
  DROP COLUMN IF EXISTS pf_on_actual_wages;

ALTER TABLE public.payroll_employees
  DROP COLUMN IF EXISTS pf_on_actual_wages_reference,
  DROP COLUMN IF EXISTS pf_on_actual_wages_from,
  DROP COLUMN IF EXISTS pf_on_actual_wages;

COMMIT;
