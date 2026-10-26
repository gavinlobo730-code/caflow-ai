-- Rollback of migration 549: gives `authenticated` (and `anon`, on the view) back the privileges the earlier migrations granted.
-- THIS RE-OPENS THE HOLE: a person with their own sign-in can read, over PostgREST and not through the API, whatever the row
-- policies let them read of the payslips, the salary history, the loans, the remittances and the tax declarations of their
-- clients, and write the tax declaration, its lines and the firm's professional-tax slabs. Roll back the code that depends on
-- the revoke first (there is none: the API runs as the server on these tables since POST-A-339 step 1).
-- It restores exactly what a database built from the migrations held before 549: SELECT on the twenty-three tables and the
-- view for `authenticated`, SELECT on the view for `anon`, and INSERT, UPDATE and DELETE on the tax declaration, its lines and
-- the professional-tax slabs. It does NOT restore the TRUNCATE privilege on `authenticated` and `anon` that 549 also revoked,
-- because no migration ever granted it (it came from the hosting platform's defaults) and a signed-in role has no use for it.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'payroll_employees', 'payroll_runs', 'payroll_slips', 'payroll_run_transitions',
        'salary_structures', 'payroll_salary_revisions', 'payroll_loans', 'payroll_perquisites',
        'payroll_one_time_earnings', 'attendance', 'leave_balances', 'bonus_declarations', 'bonus_disqualifications',
        'payroll_loan_recoveries', 'payroll_settlements', 'payroll_settlement_components',
        'statutory_remittances', 'epfo_ecr_filings',
        'payroll_it_declarations', 'payroll_it_declaration_items',
        'client_payroll_settings', 'client_pt_registrations', 'firm_pt_slabs'
    ] LOOP
        EXECUTE format('GRANT SELECT ON public.%I TO authenticated', t);
    END LOOP;
    GRANT INSERT, UPDATE, DELETE ON public.payroll_it_declarations, public.payroll_it_declaration_items,
        public.firm_pt_slabs TO authenticated;
    GRANT SELECT ON public.salary_slips TO authenticated, anon;
END $$;
