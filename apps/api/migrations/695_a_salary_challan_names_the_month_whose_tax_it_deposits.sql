-- 695 — a TDS challan under section 192 may name the wage month whose tax it deposits (POST-A-267, the salary deposit).
--
-- THE GAP
--
-- A client with a payroll engagement carries a `TDS_SALARY_DEPOSIT` obligation for every month on the compliance calendar
-- (`compliance_obligation_service._payroll_obligations`, Rule 30(2)'s date through `compliance_engine.tds_deposit_due_date`). The
-- salary tax is deposited on a challan 281 recorded in `tds_challans` under section 192, and a challan carries a financial year and a
-- QUARTER and no month, so nothing could say which month's deposit a recorded salary challan made, and the obligation read Overdue on
-- Deadlines, the Compliance tab and the dashboard however the tax had been paid. The non-salary deposits are matched to months by
-- the register's order (deductions are dated); payroll's tax sits on the run's slips, so there is no order to match by.
--
-- WHAT THIS ADDS
--
-- One nullable column, `deduction_month` ('YYYY-MM'): the wage month whose tax the challan deposits, TYPED by the person recording it
-- (as the ESI remittance register's wage month is), so the month is stated and never guessed. The API takes it only on a salary
-- challan and only for a month inside the challan's own financial year and quarter; the CHECK here holds only its shape, because
-- which sections are salary and which months a quarter holds are the API's (`domain/tds/deposit_due.is_salary`,
-- `domain/tds/section_rates.quarter_dates`). NULL means "no month stated": every challan recorded before this, every non-salary
-- challan, and a salary challan recorded without one; such a challan closes no salary obligation and is otherwise read exactly as
-- before (the 24Q, the deposit state and the register ignore the column). No backfill: which month an old challan paid is a fact
-- only the person who recorded it knows.
--
-- Nothing here transmits anything to a portal.

BEGIN;

ALTER TABLE public.tds_challans
    ADD COLUMN IF NOT EXISTS deduction_month text;

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'tds_challans_deduction_month_shape') THEN
        ALTER TABLE public.tds_challans
            ADD CONSTRAINT tds_challans_deduction_month_shape
            CHECK (deduction_month IS NULL OR deduction_month ~ '^[0-9]{4}-(0[1-9]|1[0-2])$');
    END IF;
END $$;

COMMENT ON COLUMN public.tds_challans.deduction_month IS
    'POST-A-267 (migration 695): the wage month (YYYY-MM) whose section 192 tax this challan deposits, as typed by the person who '
    'recorded it; NULL when none was stated. Set by the API on a salary challan only, inside the challan''s own year and quarter. '
    'Read by services/tds_salary_deposit_closes_obligation to close that month''s TDS_SALARY_DEPOSIT obligation.';

COMMIT;
