-- Rollback of migration 504: drops the disbursement lease column. Any claim held at the moment of the rollback is lost,
-- which is the lease behaving as if it had lapsed. Roll the API back FIRST: the deployed release and payment both write
-- this column and fail with a missing-column error once it is gone.
ALTER TABLE public.payroll_runs DROP COLUMN IF EXISTS disbursement_claimed_at;
