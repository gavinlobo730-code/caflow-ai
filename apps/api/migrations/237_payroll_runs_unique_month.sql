-- Migration 237: unique (firm_id, client_id, month) on payroll_runs.
--
-- Task #229 audit finding: create_run's duplicate-run guard
-- (routers/payroll.py) is a check-then-act SELECT-then-INSERT with no
-- backing database constraint — payroll_runs has never had a uniqueness
-- constraint on (firm_id, client_id, month) since it was first created
-- (migration 014) or in any migration since. Two concurrent
-- POST /api/payroll/runs calls for the same (firm, client, month) can both
-- pass the app-level duplicate check and both insert a run row, producing
-- two payroll runs for the same month — each independently finalizable,
-- each computing its own slips/totals, corrupting the payroll audit trail
-- (Form 16/24Q, PF/ESI returns draw from whichever run a report happens to
-- pick). This mirrors the exact race class already closed for sales invoice
-- numbers (migration 151) and bank statement import hashes (migration 224).
--
-- No existing duplicate rows are expected in production (the app-level
-- check has been in place since the feature shipped), but the migration is
-- written defensively: it only adds the constraint, it does not delete data.
-- If duplicates exist they must be resolved manually before this applies
-- cleanly — the same operational posture as every other unique-backstop
-- migration in this codebase.

CREATE UNIQUE INDEX IF NOT EXISTS uq_payroll_runs_firm_client_month
  ON public.payroll_runs (firm_id, client_id, month);
