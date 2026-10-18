-- Migration 515: the leave allotments and the client activity feed are written by the API, and by nobody signed in.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- PART 1 — LEAVE ALLOTMENTS (ledger POST-A-235)
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 499 took the signed-in write away from sixteen payroll tables and left `leave_balances` (and the employee's own
-- tax declaration) alone, because the attendance screen upserted it straight over PostgREST. That screen now saves through
-- `PUT /api/payroll/leave-balance`, which sits behind `payroll:write` and so behind the per-person permission grid, resolves
-- the employee to a client the caller may act on, refuses a row of three empty boxes, and writes the change to the audit log
-- with what it replaced. Until this migration the table asked the ROLE alone: a Manager whom a Partner had blocked from
-- payroll:write on the Team screen could still change an employee's leave allotment over the database.
--
-- `payroll_it_declarations` and `payroll_it_declaration_items` stay writable by a signed-in session on purpose: Rule 26C makes
-- Form 12BB the employee's own statement (migration 297), and the employee has no staff principal to go through the API with.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- PART 2 — THE ACTIVITY FEED (ledger POST-A-228)
-- ═══════════════════════════════════════════════════════════════════════════
-- Four screens inserted into `client_timeline_events` themselves, choosing the actor type, id and name, so a staff member could
-- write an entry in a client's activity feed that names someone else as the person who did it (the audit log is a separate
-- append-only table and was never affected). They record through `POST /api/timeline/events` now, which sets the firm from the
-- caller and the actor from the signed-in person. The server's own events were written with the CALLER's session too (under
-- USE_USER_JWT, the production default, `get_supabase()` is that session), so `services/timeline_service` writes with the
-- privileged client in the same change; without that, taking the grant away would have silenced every server-written event
-- (they are non-fatal, so silently) in the minutes before the API deployed.
--
-- WHAT THIS DOES
--   REVOKE INSERT, UPDATE, DELETE and TRUNCATE on `leave_balances`, and INSERT and TRUNCATE on `client_timeline_events`, from
--   `authenticated`, `anon` and PUBLIC. The feed's pin button is a COLUMN-level UPDATE on `is_pinned` (migration 494) and stays;
--   reading stays on both; `service_role` is untouched; the row-security policies stay as the second lock. The closing check asks
--   the EFFECTIVE privilege, so one that reaches a role through PUBLIC, a membership or a column grant is seen.
--
-- DEPLOY ORDER: the migration job runs after the tests, while Render rebuilds. For the minutes the OLD API still runs, a server
-- timeline event is refused (the old service wrote with the caller's session) and, until the new browser build is served, a
-- screen's event write and the attendance screen's leave save fail with a permission error. Neither blocks the action the person
-- took: the timeline write is non-blocking on every screen, and the leave box keeps what was typed and shows the error.
--
-- Idempotent. Reversible: 515_..._rollback.sql restores the grants the earlier migrations gave.

DO $$
DECLARE
    leave_table  text := 'public.leave_balances';
    feed_table   text := 'public.client_timeline_events';
    r text;
    verb text;
BEGIN
    IF to_regclass(leave_table) IS NOT NULL THEN
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON %s FROM PUBLIC, authenticated, anon', leave_table);
    END IF;
    IF to_regclass(feed_table) IS NOT NULL THEN
        EXECUTE format('REVOKE INSERT, TRUNCATE ON %s FROM PUBLIC, authenticated, anon', feed_table);
    END IF;

    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        IF to_regclass(leave_table) IS NOT NULL THEN
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, leave_table, verb) THEN
                    RAISE EXCEPTION 'migration 515: % still holds % on leave_balances', r, verb;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, leave_table, 'INSERT') OR has_any_column_privilege(r, leave_table, 'UPDATE') THEN
                RAISE EXCEPTION 'migration 515: % still holds a column-level write privilege on leave_balances', r;
            END IF;
        END IF;
        IF to_regclass(feed_table) IS NOT NULL THEN
            FOREACH verb IN ARRAY ARRAY['INSERT', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, feed_table, verb) THEN
                    RAISE EXCEPTION 'migration 515: % still holds % on client_timeline_events', r, verb;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, feed_table, 'INSERT') THEN
                RAISE EXCEPTION 'migration 515: % still holds a column-level INSERT on client_timeline_events', r;
            END IF;
        END IF;
    END LOOP;
END $$;
