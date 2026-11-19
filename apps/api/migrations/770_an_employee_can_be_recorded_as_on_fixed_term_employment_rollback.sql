-- Rollback of migration 770: drops the constraint and the two fixed-term columns. A fixed-term record made in the meantime is lost, and
-- that employee goes back to the ordinary five-year rule for gratuity.

ALTER TABLE public.payroll_employees
    DROP CONSTRAINT IF EXISTS payroll_employees_fixed_term_end_needs_a_fixed_term;

ALTER TABLE public.payroll_employees
    DROP COLUMN IF EXISTS fixed_term_end_date,
    DROP COLUMN IF EXISTS fixed_term_employment;
