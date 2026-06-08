-- Migration 044: Grant missing DML privileges on attendance and leave_balances.
--
-- Migration 027 created these tables but omitted GRANT SELECT/INSERT/UPDATE/DELETE.
-- Without these grants the authenticated role cannot read or write attendance or
-- leave-balance rows even though RLS policies exist.  The FK references were also
-- corrected in the source file (027) to point at public.payroll_employees rather
-- than the non-existent public.employees table.

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.attendance      TO authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.leave_balances  TO authenticated, service_role;
