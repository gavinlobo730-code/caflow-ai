-- POST-A-526 (b). Gratuity under section 53 of the Code on Social Security, 2020: an employee on FIXED-TERM employment is eligible on
-- at least one year of service under the contract, not five (the second proviso to section 53(1); rule 33(1)(a) of the Social Security
-- (Central) Rules, 2026: "if he renders service under the contract for a period of at least one year and for subsequent period in excess
-- of six months and more, but less than one year, shall be rounded off to one additional year"), paid pro rata to the service rendered
-- (the third proviso to section 53(2)). The product held no fixed-term setting and refused everybody under five years except on death
-- or disablement.
--
-- Two additive, nullable columns on public.payroll_employees and nothing else:
--
--   fixed_term_employment  NULL = never recorded (every employee that exists today, and the ordinary five-year rule, exactly as before);
--                          TRUE = the employer recorded a fixed-term contract; FALSE = recorded and withdrawn. NULL and FALSE compute
--                          alike and are kept apart for the reason the PF election's (migration 477) are: "nobody said" and "somebody
--                          withdrew it" are different facts to read back. Never inferred from an end date or a short service.
--   fixed_term_end_date    the contract's end date, optional, and only beside a fixed-term employee.
--
-- Additive and nullable, so the running API is unaffected until the code that writes them deploys, and an employee created without
-- them never names the columns.

ALTER TABLE public.payroll_employees
    ADD COLUMN IF NOT EXISTS fixed_term_employment boolean,
    ADD COLUMN IF NOT EXISTS fixed_term_end_date   date;

ALTER TABLE public.payroll_employees
    DROP CONSTRAINT IF EXISTS payroll_employees_fixed_term_end_needs_a_fixed_term;
ALTER TABLE public.payroll_employees
    ADD CONSTRAINT payroll_employees_fixed_term_end_needs_a_fixed_term
    CHECK (fixed_term_end_date IS NULL OR fixed_term_employment IS TRUE);

COMMENT ON COLUMN public.payroll_employees.fixed_term_employment IS
    'Whether the employer recorded this employee as on fixed-term employment: eligible for gratuity on at least one year of service '
    'under the contract, not five (section 53(1) second proviso of the Code on Social Security 2020; rule 33(1)(a) of the Social '
    'Security (Central) Rules 2026). NULL = never recorded (the ordinary five-year rule); TRUE = recorded; FALSE = recorded and '
    'withdrawn. Never inferred.';
COMMENT ON COLUMN public.payroll_employees.fixed_term_end_date IS
    'The end date of the fixed-term contract, optional; only beside fixed_term_employment = true (CHECK).';
