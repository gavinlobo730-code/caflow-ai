-- Rollback for migration 335.
--
-- Drops the table outright. Unlike 334 there is nothing to preserve: every row
-- here is a record a CA typed in from the EPFO portal AFTER filing, so dropping
-- it loses the sequence tracking but changes no computed figure, no payslip and
-- no ledger entry. Re-applying 335 leaves the product exactly where it was
-- before, with the months unrecorded again.
BEGIN;
DROP INDEX IF EXISTS public.epfo_ecr_one_regular_per_month;
DROP INDEX IF EXISTS public.epfo_ecr_filings_by_client_month;
DROP TABLE IF EXISTS public.epfo_ecr_filings;
COMMIT;
