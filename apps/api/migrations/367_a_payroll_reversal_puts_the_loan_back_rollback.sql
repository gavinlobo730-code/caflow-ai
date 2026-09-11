-- Rollback for 367. The table is a HISTORY — dropping it loses the record of
-- which loan each run recovered against, and that record cannot be rebuilt
-- from the balances (see the migration's header for why). Only run this if 367
-- is being rolled back before any run has finalised against it.
DROP TABLE IF EXISTS public.payroll_loan_recoveries;
