-- Migration 498: a finalized or paid payroll run, and its payslips, cannot be changed from a signed-in session.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ledger POST-B-004, the half migration 485 left)
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 485 gave payroll_runs and payroll_slips a role tier and a client scope, and left them writable by
-- Manager and above. The API refuses to touch a run once it is released: `_assert_run_is_unreleased` guards the
-- recompute and the delete, `update_run_status` excludes finalized and paid, and a reversal is a Partner's act that
-- posts the opposing journals first. But the API is not the only way to reach these tables. The database is
-- reachable straight from a signed-in browser session, where `rbac()` never runs, and a Manager's `payroll:write`
-- is enough for the policies of 485 to say yes. So from a signed-in session, with nothing more than that, a person
-- could:
--
--   * rewrite `total_net_paise`, `total_pf_paise` or `total_tds_paise` on a run whose journal was already posted,
--     so the run no longer agreed with the ledger it had been posted to, while the PF return, the ESIC return and
--     the 24Q read their figures from that run;
--   * rewrite a payslip of a released run, which is the document the employee downloads and the statutory record of
--     what was deducted;
--   * set a draft run's status to `finalized` or `paid` with no journal behind it, which is also what the employee
--     portal and every statutory builder read as "released";
--   * move a released run back to `review` without reversing its journals, after which the API's finalise would
--     post a second accrual for the month;
--   * delete a released run, which cascades to its payslips, its loan-recovery rows and, because
--     `payroll_run_transitions` references it with ON DELETE CASCADE, to the append-only release log migration 328
--     built to be the thing that cannot be erased.
--
-- None of this is reachable from any screen. The browser reads these two tables and writes neither
-- (`apps/web` has no insert, update or delete on either), so nothing legitimate depends on the access that is closed
-- here. What it closes is the access that was available to anyone willing to send the request themselves.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- Two BEFORE row triggers. For a SIGNED-IN SESSION (the role PostgREST sets for a caller, `authenticated`, or
-- `anon`) they refuse:
--
--   payroll_runs    an INSERT or UPDATE that leaves a row finalized or paid, and an UPDATE or DELETE of a row that
--                   is finalized or paid. That is every way into released (a run is released only by the API's
--                   finalise, which posts the journal and is a Partner's act), every way out of it (reversal, which
--                   reverses the journals first) and every change while there.
--   payroll_slips   an INSERT, UPDATE or DELETE of a slip whose run, before or after the statement, is finalized or
--                   paid. A slip moved from a draft run into a released one is refused for the same reason, and so
--                   is one moved out of a released run.
--
-- For the API (`service_role`) the run trigger asks one thing, which every one of the API's own writes already
-- satisfies: a run does not BECOME finalized without `journal_entry_id`, and does not BECOME paid without both
-- `journal_entry_id` and `disbursement_journal_entry_id`. `finalize_run` sets `journal_entry_id` in the same UPDATE as
-- the status, and `disburse_run` sets the disbursement journal in the same UPDATE as `paid`. The check is on the
-- transition only, so a run released before the columns existed is not asked anything. It cannot prove the journal
-- was reversed before a run reopens; that stays the API's ordering (`reverse_run` reverses, then resets).
--
-- A draft or review run, and the slips of one, are untouched for a signed-in session: the tier of 485 still decides
-- who may write them, and this migration changes nothing there. Ledger line POST-A-234 holds what that leaves.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHO IS JUDGED, AND WHO IS NOT, ON PURPOSE
-- ═══════════════════════════════════════════════════════════════════════════
-- The payroll router writes through the privileged client (`routers/payroll._db` is `service_db_or_none`, for the
-- reasons its own comment gives), so its finalise, disbursement and reversal arrive as `service_role` and are exactly
-- the changes refused from `authenticated`. The API stays the control for its own writes, as it is for every other
-- table; this is the backstop for the direct path that had no control at all.
--
-- This is deliberately WEAKER than the journal immutability triggers (251), which refuse everyone, the owner and
-- service_role included, so that the only way to change a posted ledger is a migration that disables the trigger.
-- A released payroll run has a legitimate way back (reversal), so `service_role` must be able to write it, and the
-- database owner is not judged either: a repair of a released run is meant to be a deliberate, reviewable act, and it
-- is what lets a fixture seed one. `platform_purge_firm` (141) runs with session_replication_role = replica and so
-- bypasses these triggers, which is right: it is service_role or platform-admin only.
--
-- HOW THE CALLER IS TOLD APART
--   `current_setting('role')`, which PostgREST sets to the caller's role and which stays the caller's role inside a
--   SECURITY DEFINER function (where `current_user` would be the owner). A connection that never changed role reads
--   'none'. The sibling guard `assert_caller_acts_for` (486) reads the JWT claim instead; the role setting was chosen
--   here because a caller cannot forge it. It is a deny-list of two names: a custom JWT role, or a login role that
--   inherits from `authenticated` without SET ROLE, reads another value and passes. Neither exists in this project.
--
-- WHAT FOLLOWS FROM IT, SAID HERE SO NOBODY IS SURPRISED
--   * A foreign-key cascade is judged as the session that started it. A signed-in session deleting a
--     payroll_employees row that has a payslip in a released run, or a clients row with a released run, is refused,
--     with a sentence that names the payslips or the run and not the delete that caused it. That is wanted (it
--     stops payslips being erased against the retention duty) and neither the API nor the browser does it:
--     `delete_client` is a soft delete, and `delete_employee` runs as service_role and refuses an employee who has
--     slips.
--   * A SECURITY DEFINER function that a signed-in session calls and that writes these tables is judged too, because
--     the role setting stays the caller's. A future atomic finalise exposed as an RPC and called through the
--     request-scoped client would be refused; it would have to be called with the service client, like the router.
--   * A row-level trigger fires before the row-security WITH CHECK, so for a released run the trigger's refusal
--     replaces row security's, for an actor row security would have refused as well. Both are 42501.
--
-- WHY SECURITY DEFINER
--   The slip trigger has to see its run's status whichever runs the caller can see; read as the caller, a run hidden
--   by row security would read as "no such run", which is "not released", which is the wrong way to fail. Both
--   functions set their search_path, take no arguments (a trigger function cannot be called as anything else) and
--   have EXECUTE revoked from the roles a browser session holds.
--
-- THE ERROR
--   SQLSTATE 42501 (insufficient_privilege), the code a row-security refusal carries and PostgREST maps to HTTP 403,
--   with a sentence that says what to do instead. The API-side evidence check raises 23514 (check_violation).
--
-- THE VOCABULARY
--   'finalized' and 'paid' are the released statuses (payroll_runs_status_check, migrations 093 and 225). They are
--   written out here, as they are in `my_payroll_run_ids()` (323) and the API's `_PAYROLL_UNRELEASED`. A test reads
--   the CHECK constraint and fails the day a status is added, so a new released status cannot be left uncovered.
--
-- THIS MIGRATION IS A BACKSTOP AND NOT A NEW RULE FOR THE API: the API already refuses every one of these, and every
-- one of its own writes passes the evidence check. Applying it to production changes the answer for a signed-in
-- session that was sending the requests above, for the cascades and wrapper functions described, and for nothing else.

CREATE OR REPLACE FUNCTION public.refuse_a_signed_in_change_to_a_released_payroll_run()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_role text := COALESCE(current_setting('role', true), 'none');
BEGIN
    IF v_role IN ('authenticated', 'anon') THEN
        IF TG_OP IN ('UPDATE', 'DELETE') THEN
            IF OLD.status IN ('finalized', 'paid') THEN
                RAISE EXCEPTION
                    'A % payroll run cannot be changed from a signed-in session. A Partner reverses it from the Release '
                    'tab, which reopens it; correct it there and finalize it again. Nothing was changed.', OLD.status
                    USING ERRCODE = '42501';
            END IF;
        END IF;

        IF TG_OP IN ('INSERT', 'UPDATE') THEN
            IF NEW.status IN ('finalized', 'paid') THEN
                RAISE EXCEPTION
                    'A payroll run is released only by finalizing it on the Release tab, which posts its journal; it '
                    'cannot be set to % from a signed-in session. Nothing was changed.', NEW.status
                    USING ERRCODE = '42501';
            END IF;
        END IF;

    ELSIF v_role = 'service_role' THEN
        -- The API. Released means a posted journal: the transition into finalized carries the accrual journal and the
        -- transition into paid carries both. Only the transition is asked, so a row released earlier is not.
        IF TG_OP IN ('INSERT', 'UPDATE') THEN
            IF NEW.status = 'finalized' AND NEW.journal_entry_id IS NULL
               AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'finalized') THEN
                RAISE EXCEPTION
                    'A payroll run is finalized only with the journal that posted it; this one has none. Nothing was changed.'
                    USING ERRCODE = '23514';
            END IF;
            IF NEW.status = 'paid' AND (NEW.journal_entry_id IS NULL OR NEW.disbursement_journal_entry_id IS NULL)
               AND (TG_OP = 'INSERT' OR OLD.status IS DISTINCT FROM 'paid') THEN
                RAISE EXCEPTION
                    'A payroll run is marked paid only with its accrual journal and its disbursement journal; this one is '
                    'missing one of them. Nothing was changed.'
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;

    -- Any other role (the database owner, migrations, an administrative session) is not judged here.
    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION public.refuse_a_signed_in_change_to_a_released_payroll_run() IS
    'POST-B-004. A finalized or paid payroll run is not written by a signed-in session: not changed, not deleted, '
    'and not set to a released status. For the API (service_role) a run becomes finalized only with its journal and paid '
    'only with both journals. The database owner is not judged. Migration 498.';

CREATE OR REPLACE FUNCTION public.refuse_a_signed_in_change_to_the_payslips_of_a_released_run()
RETURNS trigger
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
DECLARE
    v_released boolean;
BEGIN
    IF COALESCE(current_setting('role', true), 'none') NOT IN ('authenticated', 'anon') THEN
        IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
        RETURN NEW;
    END IF;

    -- The run the slip is leaving (an UPDATE or DELETE) and the run it is joining (an INSERT or UPDATE). A slip moved
    -- from a draft run into a released one, or out of a released one, is a change to the released run's payslips.
    IF TG_OP IN ('UPDATE', 'DELETE') THEN
        SELECT EXISTS (SELECT 1 FROM public.payroll_runs r
                        WHERE r.id = OLD.run_id AND r.status IN ('finalized', 'paid'))
          INTO v_released;
        IF v_released THEN
            RAISE EXCEPTION
                'The payslips of a finalized or paid payroll run cannot be changed from a signed-in session. A Partner '
                'reverses the run from the Release tab, which reopens it; correct it there and finalize it again. '
                'Nothing was changed.'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    IF TG_OP IN ('INSERT', 'UPDATE') THEN
        SELECT EXISTS (SELECT 1 FROM public.payroll_runs r
                        WHERE r.id = NEW.run_id AND r.status IN ('finalized', 'paid'))
          INTO v_released;
        IF v_released THEN
            RAISE EXCEPTION
                'A payslip cannot be added to, or moved into, a finalized or paid payroll run from a signed-in session. '
                'A Partner reverses the run from the Release tab, which reopens it. Nothing was changed.'
                USING ERRCODE = '42501';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END $$;

COMMENT ON FUNCTION public.refuse_a_signed_in_change_to_the_payslips_of_a_released_run() IS
    'POST-B-004. The payslips of a finalized or paid payroll run are not written by a signed-in session, whether the '
    'slip is already in the run or is being added or moved into it. Migration 498.';

REVOKE ALL ON FUNCTION public.refuse_a_signed_in_change_to_a_released_payroll_run() FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.refuse_a_signed_in_change_to_the_payslips_of_a_released_run() FROM PUBLIC, anon, authenticated;

DROP TRIGGER IF EXISTS a_released_payroll_run_is_not_written_by_a_session ON public.payroll_runs;
CREATE TRIGGER a_released_payroll_run_is_not_written_by_a_session
    BEFORE INSERT OR UPDATE OR DELETE ON public.payroll_runs
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_change_to_a_released_payroll_run();

DROP TRIGGER IF EXISTS a_released_runs_payslips_are_not_written_by_a_session ON public.payroll_slips;
CREATE TRIGGER a_released_runs_payslips_are_not_written_by_a_session
    BEFORE INSERT OR UPDATE OR DELETE ON public.payroll_slips
    FOR EACH ROW EXECUTE FUNCTION public.refuse_a_signed_in_change_to_the_payslips_of_a_released_run();

DO $$
DECLARE
    n int;
BEGIN
    SELECT count(*) INTO n
      FROM pg_trigger t
     WHERE NOT t.tgisinternal AND t.tgenabled = 'O'
       AND t.tgname IN ('a_released_payroll_run_is_not_written_by_a_session',
                        'a_released_runs_payslips_are_not_written_by_a_session');
    IF n <> 2 THEN
        RAISE EXCEPTION 'migration 498: expected 2 enabled triggers, found %', n;
    END IF;
    IF has_function_privilege('authenticated', 'public.refuse_a_signed_in_change_to_a_released_payroll_run()', 'EXECUTE')
       OR has_function_privilege('authenticated', 'public.refuse_a_signed_in_change_to_the_payslips_of_a_released_run()', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 498: a trigger function is executable by authenticated';
    END IF;
END $$;
