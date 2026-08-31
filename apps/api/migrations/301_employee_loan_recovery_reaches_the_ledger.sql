-- ============================================================================
-- 301 — a loan recovered through payroll has to reach the ledger
--
-- WHAT WOULD HAVE HAPPENED WITHOUT THIS
--     Migration 300 let an advance be recovered through the payslip, which
--     reduces net pay. The payroll accrual journal credits Net Salary Payable,
--     PF, ESI, PT and TDS, and debits Salaries Expense with the SUM of those
--     credits — so a deduction with no credit leg makes the debit too small and
--     understates salary expense.
--
--     _build_payroll_lines already guards for exactly this, and its comment
--     names the case: "A value below gross means `net` was reduced by a
--     deduction with no matching credit leg here (e.g. a future loan/advance
--     recovery)". So finalising a run with a recovery would have raised rather
--     than posted a wrong journal — loud, which is right, and still broken.
--
-- THE ACCOUNTING
--     Recovering an advance does not reduce the employer's salary cost; it
--     settles part of that cost by extinguishing a receivable instead of paying
--     cash:
--
--         Dr  Salaries Expense                (total cost, unchanged)
--           Cr  Net Salary Payable            (net, now lower)
--           Cr  PF / ESI / PT / TDS Payable
--           Cr  Employee Loans & Advances     (the recovery)
--
--     Crediting the receivable is what reduces the asset. Booking the recovery
--     as a reduction in salary expense instead would understate both the
--     expense and the asset, and the two errors would hide each other.
--
-- The account is seeded per firm the way migration 093 seeds the other payroll
-- control accounts, and only where the firm already has a chart — a firm with
-- no accounts has not been set up yet, and seeding one account into an empty
-- chart would create a chart with exactly one account in it.
-- ============================================================================

-- The per-slip figure, and the run total that the journal reads.
ALTER TABLE public.payroll_slips
  ADD COLUMN IF NOT EXISTS loan_recovery_paise bigint NOT NULL DEFAULT 0;

ALTER TABLE public.payroll_runs
  ADD COLUMN IF NOT EXISTS total_loan_recovery_paise bigint NOT NULL DEFAULT 0;

COMMENT ON COLUMN public.payroll_slips.loan_recovery_paise IS
  'Advance recovered from this payslip, AFTER the statutory deductions and only '
  'out of what is left — PF, ESI, professional tax and TDS are owed to somebody '
  'else and come first. Written down against payroll_loans at finalisation.';

COMMENT ON COLUMN public.payroll_runs.total_loan_recovery_paise IS
  'Advances recovered from net pay this run. Credited to Employee Loans & '
  'Advances in the accrual journal — it settles part of the salary cost by '
  'extinguishing a receivable, and does not reduce the cost itself.';

INSERT INTO public.chart_of_accounts
  (id, firm_id, account_name, account_code, account_type, account_subtype)
SELECT gen_random_uuid(), f.id, req.name, req.code, req.type, req.subtype
FROM public.firms f
CROSS JOIN (VALUES
  ('Employee Loans & Advances', '1240', 'Asset', 'Current Asset', '%employee loans%')
) AS req(name, code, type, subtype, pattern)
WHERE EXISTS (SELECT 1 FROM public.chart_of_accounts c0 WHERE c0.firm_id = f.id)
  AND NOT EXISTS (
        SELECT 1 FROM public.chart_of_accounts c
        WHERE c.firm_id = f.id AND c.account_name ILIKE req.pattern)
  AND NOT EXISTS (
        SELECT 1 FROM public.chart_of_accounts c
        WHERE c.firm_id = f.id AND c.account_code = req.code);
