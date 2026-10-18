-- Rollback of migration 508: drops the owed-write-down record and the reversal lease. A write-down that was owed at the
-- moment of the rollback is forgotten (the Loans list shows the balance too high, as it did before), and a reversal in
-- flight loses its claim. Roll the API back FIRST: the deployed release and reversal both write these columns and fail
-- with a missing-column error once they are gone.
ALTER TABLE public.payroll_runs
    DROP COLUMN IF EXISTS loan_writedown_owed_at,
    DROP COLUMN IF EXISTS reversal_claimed_at;
