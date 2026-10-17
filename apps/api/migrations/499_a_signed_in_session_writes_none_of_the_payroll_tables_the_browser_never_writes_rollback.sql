-- Rollback of migration 499: gives `authenticated` back the write privileges the earlier migrations granted on these tables.
-- THIS RE-OPENS THE HOLE: an assigned Manager can again write a draft payroll run, its payslips, the run history and the
-- loans and salary history a run is computed from, directly over the database (498 still freezes a released run).
-- It restores INSERT, UPDATE and DELETE to `authenticated` exactly as the earlier migrations granted them (INSERT alone on
-- the release log, INSERT and UPDATE on the remittance and ECR-filing tables), which is also what production held on
-- 17-10-2026. It does NOT restore the TRUNCATE privilege on `authenticated` and `anon` that 499 also revoked, because
-- no migration ever granted it (it came from the hosting platform's defaults) and a signed-in role has no use for it.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'payroll_employees', 'payroll_runs', 'payroll_slips',
        'salary_structures', 'payroll_salary_revisions', 'payroll_loans', 'payroll_perquisites',
        'payroll_one_time_earnings', 'attendance', 'bonus_declarations', 'bonus_disqualifications',
        'payroll_loan_recoveries', 'payroll_settlements', 'payroll_settlement_components'
    ] LOOP
        EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
    END LOOP;
    GRANT INSERT ON public.payroll_run_transitions TO authenticated;
    GRANT INSERT, UPDATE ON public.statutory_remittances, public.epfo_ecr_filings TO authenticated;
END $$;
