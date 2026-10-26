-- Migration 549: a signed-in session reads and writes none of the payroll tables (POST-A-339, the payroll group).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- POST-A-010 (25-10-2026) moved every read and write of the payroll tables out of the browser: employees, runs, slips,
-- attendance, leave, salary, loans, settlements and the tax declaration are asked of the API now, which answers with its
-- own server key, and `tests/test_a_sensitive_table_is_not_read_from_the_browser.py` holds that the browser names none of
-- them. What that did not do was take the grants away. `authenticated` still held SELECT on every one of these tables (and
-- INSERT, UPDATE and DELETE on the tax declaration, its lines and the firm's professional-tax slabs), so a person with their
-- own sign-in could still call PostgREST by hand and read exactly what the row policies let them read: the payslips of their
-- clients, the salary history, the loans, the PF and ESI remittances. The row policies are good (migrations 262, 296, 297,
-- 485, 490, 498 and 499 are the work of making them so) and they are all that stood between a hand-made call and the data,
-- when nothing legitimate needs the call to work at all.
--
-- The API was moved first (POST-A-339 step 1, ledger entry in docs/design-record/tenancy-and-security.md): every query it
-- makes on these tables is made with its privileged client, naming the firm, and carries the signed-in person to the edit
-- log (migration 547). That change shipped and ran in production BEFORE this migration, because the old API against revoked
-- grants fails soft and wrong (an empty list, a lookup that says not found, a posting skipped).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- REVOKE SELECT, INSERT, UPDATE, DELETE and TRUNCATE from PUBLIC, `authenticated` and `anon` on the twenty-three payroll
-- tables below and SELECT on the view `salary_slips` over them. (PUBLIC is named so that a privilege reaching a signed-in
-- role through it cannot survive; none is known to exist. TRUNCATE is a default privilege of the hosting platform and
-- PostgREST does not expose it; it goes so that no verb is left. The platform's REFERENCES and TRIGGER privileges are not
-- privileges on rows and are left alone, as migration 499 left them.)
--
--   employees, runs, slips and the run history      payroll_employees, payroll_runs, payroll_slips,
--                                                   payroll_run_transitions
--   what a run is computed from                     salary_structures, payroll_salary_revisions, payroll_loans,
--                                                   payroll_perquisites, payroll_one_time_earnings, attendance,
--                                                   leave_balances, bonus_declarations, bonus_disqualifications
--   what a run leaves behind                        payroll_loan_recoveries, payroll_settlements,
--                                                   payroll_settlement_components, statutory_remittances,
--                                                   epfo_ecr_filings
--   the employee's tax declaration                  payroll_it_declarations, payroll_it_declaration_items
--   a firm's and a client's statutory settings      client_payroll_settings, client_pt_registrations, firm_pt_slabs
--   a view over the slips                           salary_slips
--
-- `service_role` is untouched, so the API is unaffected, and the migration REFUSES (rolls back) if the service role would be
-- left without a privilege it needs. THE ROW POLICIES STAY, and so do the helper functions they call, as the SECOND LOCK, the
-- way migration 499 left the policies of 485 and 490: a later migration that grants a list of tables again (041 and 055
-- did) would undo a revoke and would not undo a policy. `tests/fixtures/rls_expected_second_lock.json` holds what the
-- policies decide, and a real-Postgres test gives the privilege back in a copy of the database and asks every actor again.
-- The employee-own-record policies of migrations 262, 296 and 297 are therefore kept and not dropped (the ledger entry
-- proposed dropping them as dead): they cost nothing, they grant an employee only their own rows, and a policy removed here
-- would be one less reason a regrant is harmless.
--
-- WHAT A SIGNED-IN SESSION NOW SEES
--   Any read or write of one of these tables is "permission denied for table" (SQLSTATE 42501) instead of a row-security
--   answer. A foreign-key cascade is not a privilege check, so deleting a client still cascades as it did. A SECURITY
--   DEFINER function that reads one of these tables as its owner (`my_employee_ids`, `my_payroll_run_ids`,
--   `my_it_declaration_ids`, the refusals of 498) is unaffected: it asks for the caller's own ids and never reads as the caller.
--
-- PRODUCTION, read from its catalogue on 26-10-2026: `authenticated` held SELECT on all twenty-three and the three writes
-- named above; `anon` held no SELECT on any table but the view `salary_slips`, which runs with the caller's privileges
-- (security_invoker) and so read nothing; the platform's TRUNCATE sat on `authenticated` and `anon` on `firm_pt_slabs`, the one
-- table here that 499 did not reach and that held it. No policy of another table and no view refers to these tables (pg_depend), and the only functions that do are
-- the SECURITY DEFINER ones above and `file_it_declaration` (executable by the service role alone).

DO $$
DECLARE
    tables text[] := ARRAY[
        'payroll_employees', 'payroll_runs', 'payroll_slips', 'payroll_run_transitions',
        'salary_structures', 'payroll_salary_revisions', 'payroll_loans', 'payroll_perquisites',
        'payroll_one_time_earnings', 'attendance', 'leave_balances', 'bonus_declarations', 'bonus_disqualifications',
        'payroll_loan_recoveries', 'payroll_settlements', 'payroll_settlement_components',
        'statutory_remittances', 'epfo_ecr_filings',
        'payroll_it_declarations', 'payroll_it_declaration_items',
        'client_payroll_settings', 'client_pt_registrations', 'firm_pt_slabs'
    ];
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;
    -- A view carries only SELECT (it has no TRUNCATE of its own to take).
    REVOKE SELECT ON public.salary_slips FROM PUBLIC, authenticated, anon;

    -- The check asks the EFFECTIVE privilege (has_table_privilege and has_any_column_privilege), which sees a privilege that
    -- reaches the role through PUBLIC, through membership of another role or at column level, none of which a look at
    -- information_schema.role_table_grants for the two role names would.
    FOREACH t IN ARRAY tables || ARRAY['salary_slips'] LOOP
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF t = 'salary_slips' AND verb <> 'SELECT' THEN
                    CONTINUE;
                END IF;
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 549: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'SELECT')
               OR has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 549: % still holds a column-level privilege on %', r, t;
            END IF;
        END LOOP;
        -- The API is unaffected: the service role keeps what it had.
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'SELECT') THEN
            RAISE EXCEPTION 'migration 549: service_role no longer reads %', t;
        END IF;
        IF t <> 'salary_slips' THEN
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE'] LOOP
                IF NOT has_table_privilege('service_role', format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 549: service_role no longer holds % on %', verb, t;
                END IF;
            END LOOP;
        END IF;
    END LOOP;
END $$;
