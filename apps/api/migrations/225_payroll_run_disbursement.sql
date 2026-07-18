-- Migration 225: salary disbursement (mark-paid) on payroll runs.
--
-- Finalization posts the accrual (Dr Salaries Expense / Cr Net Salary Payable +
-- statutory payables) but the net pay then sits in Net Salary Payable forever —
-- there was no step recording the actual bank payout. This adds a disbursement
-- step: a finalized run can be marked PAID, which posts Dr Net Salary Payable /
-- Cr Bank and records the payment metadata below.
ALTER TABLE public.payroll_runs
  ADD COLUMN IF NOT EXISTS paid_at                       TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS disbursement_journal_entry_id UUID REFERENCES public.journal_entries(id),
  ADD COLUMN IF NOT EXISTS paid_from_account_id          UUID REFERENCES public.bank_accounts(id),
  ADD COLUMN IF NOT EXISTS payment_reference             TEXT;

-- Widen the status set to allow 'paid' (finalized -> paid after disbursement is
-- posted). No existing row violates the wider set, so this is safe.
ALTER TABLE public.payroll_runs DROP CONSTRAINT IF EXISTS payroll_runs_status_check;
ALTER TABLE public.payroll_runs
  ADD CONSTRAINT payroll_runs_status_check CHECK (status IN ('draft','review','finalized','paid'));
