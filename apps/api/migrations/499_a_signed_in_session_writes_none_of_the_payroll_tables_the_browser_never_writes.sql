-- Migration 499: a signed-in session writes none of the payroll tables the browser never writes.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ledger POST-A-234, found by the independent review of migration 498)
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 485 gave the payroll tables a role tier and left them writable by Manager and above, and migration 490
-- gave the other payroll tables the same. Migration 498 then closed one half of what that left open: a finalized or
-- paid run, and its payslips, can no longer be changed from a signed-in session. What stayed open is everything that
-- is not released yet, and the review of 498 listed it:
--
--   * a Manager can write a DRAFT or REVIEW run and its payslips directly, so they can stamp `finalized_at`,
--     `paid_at`, `payment_reference` and the totals, and **the finalise journal is built from the run row's totals**,
--     so a Manager can choose the figure a Partner's finalise then posts;
--   * a Manager can INSERT a `payroll_run_transitions` row claiming a release that never happened (498 stops the log
--     being erased, not forged);
--   * a Manager can write the loan-recovery, remittance and ECR-filing rows of a released run, the salary history, the
--     loans and perquisites a run is computed from, and the employees themselves.
--
-- None of it is reachable from any screen. A search of `apps/web` for every payroll table found exactly three that the
-- browser writes: `leave_balances` (the attendance screen's upsert) and an employee's own tax declaration and its
-- items (the portal's declaration tab). Every other payroll table is read from the browser and written by the payroll
-- router, which uses the privileged client at every write site (`routers/payroll._db` is `service_db_or_none`), and
-- the other API writers (the bonus register, the employee portal, the ECR filing and the remittance services) take
-- their client from that router's `_db` or from `service_db`. Nothing legitimate writes the seventeen as a signed-in
-- session.
--
-- The write grants were not one decision. They came table by table: from the migration that created each table
-- (014 for employees, runs and slips; 027 for attendance, with 044 after it; 054 and 093 for salary structures; and 299,
-- 300, 302, 328, 331, 335, 365, 367 and 395 for the rest) and from the repair sweeps that granted lists of tables again
-- (041 and 055, which re-grant employees, runs, slips, attendance and salary structures). Migrations 485 and 490 then
-- put the API's Manager-and-above write tier into the database as row policies, as the defence against a direct call
-- with a person's own sign-in (490's header says so: nothing reads or writes these tables under a caller's sign-in).
-- They assumed the grants would stay. This migration takes the grants away, on the evidence that nothing needs them, and
-- the policies stay.
--
-- PRODUCTION, read from its catalogue on 17-10-2026: `authenticated` holds INSERT, UPDATE and DELETE on fourteen of the
-- seventeen, INSERT alone on the release log (`payroll_run_transitions`) and INSERT and UPDATE on the remittance and
-- ECR-filing tables, which is exactly what a database built from the migrations holds. It also holds TRUNCATE on all
-- seventeen, and `anon` holds TRUNCATE on them (a default privilege of the hosting platform, not a migration's grant).
-- PostgREST does not expose TRUNCATE, so that was not reachable from a browser; it is revoked anyway so that none of the
-- four write verbs is left. The platform's REFERENCES and TRIGGER privileges, where it grants them, are not write
-- privileges on rows and are left alone.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- REVOKE INSERT, UPDATE, DELETE and TRUNCATE from `authenticated`, `anon` and PUBLIC on the seventeen payroll tables
-- below (PUBLIC is named so that a privilege reaching a signed-in role through it cannot survive; none is known to
-- exist). Reading is untouched, `service_role` is untouched (so the API is unaffected), and the row-security policies of
-- 485 and 490 and the triggers of 498 stay where they are as the second lock: a later migration that grants a list of
-- tables again (041 did) would undo a revoke and would not undo a policy or a trigger.
--
--   employees, runs, slips and the run history      payroll_employees, payroll_runs, payroll_slips,
--                                                   payroll_run_transitions
--   what a run is computed from                     salary_structures, payroll_salary_revisions, payroll_loans,
--                                                   payroll_perquisites, payroll_one_time_earnings, attendance,
--                                                   bonus_declarations, bonus_disqualifications
--   what a run leaves behind                        payroll_loan_recoveries, payroll_settlements,
--                                                   payroll_settlement_components, statutory_remittances,
--                                                   epfo_ecr_filings
--
-- NOT revoked, because the browser writes them: `leave_balances`, `payroll_it_declarations` and
-- `payroll_it_declaration_items`. They still ask the role alone, as the Team screen's notice says, and are the ledger
-- line this migration leaves.
--
-- WHAT A SIGNED-IN SESSION NOW SEES
--   A write to one of the seventeen is a "permission denied for table" error (SQLSTATE 42501) instead of a row-security
--   refusal or a success. A read is as before. A foreign-key cascade is not a privilege check, so deleting a client
--   still cascades as it did (and 498 still refuses the cascade into a released run).
--
-- THE TEAM SCREEN'S SENTENCE
--   `DENIAL_REACH_NOTICE` said a block on writing payroll is enforced by the database for all of those tables except
--   attendance, leave and tax declarations. It is rewritten in the same commit: the database now refuses a signed-in
--   write to them for everyone, and a payroll block applies where the write happens, in the PracticeSync server.

DO $$
DECLARE
    tables text[] := ARRAY[
        'payroll_employees', 'payroll_runs', 'payroll_slips', 'payroll_run_transitions',
        'salary_structures', 'payroll_salary_revisions', 'payroll_loans', 'payroll_perquisites',
        'payroll_one_time_earnings', 'attendance', 'bonus_declarations', 'bonus_disqualifications',
        'payroll_loan_recoveries', 'payroll_settlements', 'payroll_settlement_components',
        'statutory_remittances', 'epfo_ecr_filings'
    ];
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;

    -- The check asks the EFFECTIVE privilege (has_table_privilege and has_any_column_privilege), which sees a
    -- privilege that reaches the role through PUBLIC, through membership of another role or at column level, none of
    -- which a look at information_schema.role_table_grants for the two role names would.
    FOREACH t IN ARRAY tables LOOP
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 499: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 499: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
    END LOOP;
END $$;
