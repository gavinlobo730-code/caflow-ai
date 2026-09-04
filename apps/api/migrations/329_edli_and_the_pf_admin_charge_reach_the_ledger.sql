-- Migration 329: EDLI and the EPF administrative charge reach the general
-- ledger, where they had never been.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS BROKEN
-- ═══════════════════════════════════════════════════════════════════════════
-- routers/payroll.py::_compute_pf returns five employer figures, and migration
-- 295 gave payroll_slips a column for each:
--
--     pf_employer_eps_paise   EPS 1995 para 3 — the pension diversion
--     pf_employer_epf_paise   the remainder of the 12%
--     edli_paise              0.5% under EDLI 1976
--     pf_admin_paise          0.5% administrative charge
--
-- The last two are EMPLOYER COSTS OUTSIDE the 12%, deducted from nobody, and
-- remitted on the same monthly challan as the rest. They are computed, they are
-- stored on every slip, and the statutory card on the payroll screen adds them
-- up correctly.
--
-- They never reached the ledger. create_run totals only
--
--     totals["pf"] += pf_employee_paise + pf_employer_paise
--
-- and journal_for_payroll credits PF Payable with exactly that. So every
-- payroll accrual this system has ever posted understates the employer's cost
-- of employment, and the PF liability, by roughly 1% of PF wages — about ₹150 a
-- month per member at the ₹15,000 ceiling.
--
-- It is not a rounding difference and it does not self-correct. The challan
-- paid to EPFO includes EDLI and admin; the ledger's PF Payable does not; so
-- the payment clears a liability that was never fully raised and the shortfall
-- lands wherever the bank entry is coded. The trial balance still balanced,
-- which is why it survived — the entry was internally consistent and simply
-- short.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHY COLUMNS ON THE RUN AND NOT A SUM OVER THE SLIPS
-- ═══════════════════════════════════════════════════════════════════════════
-- Every other figure the journal posts is already a total_*_paise column on
-- payroll_runs, and _build_payroll_lines takes the run alone. Summing slips at
-- posting time would make the journal read rows the rest of the entry does not,
-- for two of its six legs.
--
-- The administrative charge settles it. Its statutory MINIMUM is ₹500 per
-- ESTABLISHMENT per month, not per member (domain/payroll/statutory.py's
-- admin_minimum_paise) — so the figure the ledger owes is a property of the RUN
-- and cannot be reconstructed by adding up payslips at all. A client with three
-- members at ₹60 each owes ₹500, not ₹180.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- NOT BACKFILLED, AND THAT IS DELIBERATE
-- ═══════════════════════════════════════════════════════════════════════════
-- DEFAULT 0, and every historical run keeps 0.
--
-- The figures could be recomputed from the slips, and doing so would make old
-- runs claim a liability their POSTED JOURNAL does not carry. A posted entry is
-- immutable (CLAUDE.md, and DB triggers), so the ledger cannot be brought into
-- line by a backfill — only by a correcting entry somebody decides to make. A
-- column that disagreed with the journal beside it would be worse than one that
-- honestly reads zero.
--
-- So this fixes the accrual from here on, and the understatement in months
-- already posted stays visible as exactly what it is: a difference between the
-- slips and the entry, for a CA to correct deliberately.
--
-- Additive, idempotent, no data touched.

BEGIN;

ALTER TABLE public.payroll_runs
  ADD COLUMN IF NOT EXISTS total_edli_paise     bigint NOT NULL DEFAULT 0,
  ADD COLUMN IF NOT EXISTS total_pf_admin_paise bigint NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.payroll_runs.total_edli_paise IS
    'Employer contribution under the Employees Deposit Linked Insurance Scheme '
    '1976, 0.5% of PF wages to its own ceiling. An employer cost outside the '
    '12%, deducted from nobody, remitted on the same challan. 0 on every run '
    'finalised before migration 329, and NOT backfilled: the journal those runs '
    'posted does not carry it and a posted entry is immutable, so a recomputed '
    'column would disagree with the ledger beside it.';

COMMENT ON COLUMN public.payroll_runs.total_pf_admin_paise IS
    'EPF administrative charge, 0.5% of PF wages subject to a statutory MINIMUM '
    'of Rs 500 per ESTABLISHMENT per month. The floor is why this is a property '
    'of the run and cannot be reconstructed by summing payslips: three members '
    'at Rs 60 each owe Rs 500, not Rs 180. Not backfilled — see '
    'total_edli_paise.';

COMMIT;
