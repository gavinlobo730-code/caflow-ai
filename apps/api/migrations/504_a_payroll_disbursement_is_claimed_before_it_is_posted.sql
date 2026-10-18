-- Migration 504: a payroll disbursement is claimed before it is posted.
--
-- ════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ledger POST-A-239)
-- ════════════════════════════════════════════════════════════════════════
-- `disburse_run` read the run, checked it was `finalized`, resolved the bank, posted the salary disbursement journal and
-- only then wrote `paid`, unconditionally. Two requests that arrive before the first one finishes (a double click, a
-- retry after a timeout, two Partners) both read `finalized` and both post. The journal's own duplicate check is on
-- (client, reference PAY-DISB-{month}, entry date), so two requests carrying different payment dates are not duplicates
-- of each other, and the bank is credited twice for one payroll.
--
-- The claim the approval engine uses (one conditional UPDATE, the request that changed a row proceeds) cannot be made on
-- the status here: migration 498 lets a run become `paid` only with its disbursement journal already on the row, so the
-- status cannot be moved before the journal exists. A fourth status ("paying") would not help either: every reader that
-- lists the released statuses (`domain/payroll/run_status.PAYROLL_RELEASED`: the ECR, the 24Q, payslips, the employee
-- portal) would drop the run for as long as it lasted.
--
-- ════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ════════════════════════════════════════════════════════════════════════
-- Adds one nullable column, `payroll_runs.disbursement_claimed_at timestamptz`. The API claims the run by setting it in an
-- UPDATE that matches only a finalized run whose column is empty (and, failing that, one whose claim is older than fifteen
-- minutes), and posts only if an UPDATE changed a row. The timestamp it wrote is that request's claim: the write that marks
-- the run paid and the release are conditional on it, so a request whose claim lapsed and was taken over can neither finish
-- nor release the new holder's. The column is cleared when the run is marked paid, when the posting fails, when the run is
-- released (`finalize_run`) and when it is reversed (`reverse_run`), so a payment that was in flight when a run was reopened
-- leaves nothing on it. It is a LEASE, not a lock: if the process dies between the claim and the paid write, the claim lapses
-- by itself and the Partner can pay.
--
-- Nothing else changes. No data is written and no policy or trigger is touched. The column is written by the API
-- (service_role), which migration 498 already allows to update a finalized row as long as it does not change the status
-- without its journals; the signed-in roles hold no UPDATE on this table at all (migration 499), and migration 498's trigger
-- would refuse a change to a released row from them if that privilege were ever granted back.
--
-- DEPLOY ORDER. The API's release and payment both write this column, so code that reaches production before this migration
-- fails them with a missing-column error: the payment fails before anything is posted, and the release posts its idempotent
-- accrual journal first and then fails at its claim, so a retry after the migration is safe. The boot schema guard derives
-- the column from this file and turns `/health` to 503 once it has read the schema.
--
-- Rollback: migration 504_..._rollback.sql drops the column. The deployed API must be rolled back first or it fails.

ALTER TABLE public.payroll_runs
    ADD COLUMN IF NOT EXISTS disbursement_claimed_at timestamptz;

COMMENT ON COLUMN public.payroll_runs.disbursement_claimed_at IS
    'POST-A-239. Set by the API when a request takes the run to post its salary disbursement, and cleared when the run is '
    'marked paid, the posting fails, the run is released or the run is reversed. A claim older than fifteen minutes is '
    'treated as lapsed. NULL means nobody is paying the run now. Migration 504.';
