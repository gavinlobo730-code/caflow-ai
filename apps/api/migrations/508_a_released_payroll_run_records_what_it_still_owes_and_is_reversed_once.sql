-- Migration 508: a released payroll run records the loan write-down it still owes, and a reversal is claimed.
--
-- ════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ledger POST-A-253 and POST-A-254)
-- ════════════════════════════════════════════════════════════════════════
-- 1. `finalize_run` claims the run as `finalized` and only then writes each borrower's loan balance down. If the process
--    dies between the two, or the write-down fails part-way, the run is released, its journal is posted, and nothing
--    records that the write-down is owed (a retry answers 409). A later reversal then finds no recovery rows and takes
--    the slip-based fallback, which adds `min(slip amount, principal - outstanding)` back onto a loan the run never
--    reduced: an instalment that was never taken, whenever the borrower has earlier repayments.
-- 2. Two overlapping `reverse_run` requests can both get past `reverse_entry`'s "already reversed" refusal, because the
--    posting kernel's fast path hands the second request the first one's reversal entry, and both go on to put the loans
--    back.
--
-- ════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ════════════════════════════════════════════════════════════════════════
-- Adds two nullable columns to `payroll_runs`:
--   * `loan_writedown_owed_at`  set in the SAME UPDATE that claims the release, cleared when the write-down completes
--     (or by the owed write-down, or by a reversal). A reversal that finds it set and no recovery rows restores nothing
--     by guessing and says so.
--   * `reversal_claimed_at`     a LEASE, like `disbursement_claimed_at` (migration 504): one conditional UPDATE decides
--     which reversal proceeds, a claim older than fifteen minutes is treated as lapsed, and the reopen is conditional on
--     the claim.
-- No data is written and no policy or trigger is touched. Both columns are written by the API (service_role); the
-- signed-in roles hold no UPDATE on this table (migration 499), and migration 498's trigger already refuses a change to a
-- released row from anyone who is not allowed to make one.
--
-- NOT BACKFILLED. A run released before this migration has no record either way, so `loan_writedown_owed_at` is NULL for
-- all of them and a reversal of such a run behaves exactly as it did.
--
-- DEPLOY ORDER. The API's release and reversal both write these columns, so code that reaches production before this
-- migration fails them with a missing-column error: the release posts its idempotent accrual journal first and then fails
-- at its claim (a retry after the migration is safe), and the reversal fails before it reverses anything. The boot schema
-- guard derives the columns from this file and turns `/health` to 503 once it has read the schema.
--
-- Rollback: migration 508_..._rollback.sql drops both columns. The deployed API must be rolled back first or it fails.

ALTER TABLE public.payroll_runs
    ADD COLUMN IF NOT EXISTS loan_writedown_owed_at timestamptz,
    ADD COLUMN IF NOT EXISTS reversal_claimed_at    timestamptz;

COMMENT ON COLUMN public.payroll_runs.loan_writedown_owed_at IS
    'POST-A-253. Set by the API in the UPDATE that claims a release, cleared when the loan write-down completes, when the '
    'owed write-down finishes it, or when the run is reversed. NULL means nothing is owed (and, for a run released before '
    'migration 508, that nothing was recorded). Migration 508.';
COMMENT ON COLUMN public.payroll_runs.reversal_claimed_at IS
    'POST-A-254. A lease taken by the API when a request reverses a released run, cleared when the run is reopened or the '
    'reversal fails. A claim older than fifteen minutes is treated as lapsed. NULL means nobody is reversing the run. '
    'Migration 508.';
