-- Migration 534 — the monthly balances the reports read are written by the database's own triggers and the service role, never
-- by a signed-in session (security, ledger POST-A-318, found by the independent review of migration 533 and reproduced on a
-- throwaway database on 22-10-2026).
--
-- WHAT WAS WRONG
--   `account_period_balances` holds one row per client, account and month: the debit and credit totals of the posted ledger,
--   maintained by two triggers (`apb_on_entry_post`, `apb_on_line_insert`, which call `apb_apply_posted_line`) and healed by
--   the nightly balance-cache audit through the service role (`apb_rebuild_client`). The trial balance, profit and loss,
--   balance sheet, ratio analysis, budgets, cash flow and the year-end statements read these buckets DIRECTLY (not the
--   journal), so they are what the CA sees and signs. The table was granted INSERT, UPDATE and DELETE to `authenticated`
--   (migration 227's grant) and its only policy is the firm-and-client one (`firm_client_isolation`: the client belongs to
--   the caller's firm), with no role tier. `apb_apply_posted_line(...)` carried the default PUBLIC execute right as well, so a
--   signed-in session could call it directly.
--
--   The review ran `UPDATE account_period_balances SET debit_paise = 99999999` as an Executive assigned to the client on a
--   bucket of a CLOSED year (UPDATE 1), and called `apb_apply_posted_line` as an assigned Reviewer. No journal entry, no
--   closure check, no audit row: the reports move and the ledger does not. And because `apb_assert_no_drift()` compares
--   every firm's buckets with its posted ledger and is called by the manual-journal edit and discard functions, one
--   member's forgery made those functions refuse for EVERY firm until the nightly audit healed it.
--
--   Nothing in `apps/web` reads or writes the table, and the only Python writer is `services/balance_cache_service` (called
--   from `jobs/scheduler.py` with the privileged client). The browser has no business here.
--
-- WHAT THIS DOES
--   * REVOKEs INSERT, UPDATE, DELETE and TRUNCATE on the table from `authenticated`, `anon` and PUBLIC, and checks the
--     EFFECTIVE privilege (table, column, through PUBLIC), the shape of migrations 499, 513 and 519. SELECT is untouched:
--     the reports read it as the caller, scoped to the caller's clients through `clients` (the catalog rule's `parent`).
--   * REVOKEs EXECUTE on `apb_apply_posted_line(...)` from `authenticated`, `anon` and PUBLIC and grants it to `service_role`
--     (the trigger calls it as whoever fired the trigger: the owner inside the definer posting functions, or the service
--     role). The two trigger functions need no change: a trigger function's EXECUTE right is checked when the trigger is
--     created, not when it fires, and neither can be called directly.
--   * REVOKEs EXECUTE on the four maintenance functions migration 251 left to the service role (`apb_rebuild_client`,
--     `apb_drifted_clients`, `apb_rebuild_drifted`, `apb_assert_no_drift`) from `authenticated` and `anon` by name. 251 revoked
--     them from PUBLIC only, which keeps them from a role that has nothing but PUBLIC, and Supabase's default privileges grant
--     EXECUTE on a new function to `anon` and `authenticated` directly, so on production a signed-in session may still hold it
--     (a database built from the migrations does not, which is why the test of 251 passes either way). Nothing signed-in calls
--     them: the edit and discard functions call them as their owner, and nothing in `apps/api` or `apps/web` does.
--   * The row policy stays as it is. With no write verb granted, a second lock on writes would decide nothing.
--
-- WHAT STILL WRITES THE TABLE, AND WHY NOTHING BREAKS
--   * Posting, editing, discarding and reversing a journal entry run inside SECURITY DEFINER functions (`post_journal_atomic`,
--     `settle_receipt_atomic`, `edit_posted_journal`, `discard_posted_journal`, each as its owner), so their triggers fire as
--     the owner whatever role called them; a signed-in person needs no right on the table for the bucket to move.
--   * The service role (the API's privileged client, the scheduler's nightly audit, `apb_rebuild_client`) keeps INSERT,
--     UPDATE and DELETE and gains EXECUTE on `apb_apply_posted_line` explicitly.
--
-- NOT DONE HERE
--   * `apb_assert_no_drift()` still compares every firm at once; with the explicit revoke above it is not callable by a
--     signed-in session and, with the table no longer writable by one, cannot be made to fail by a member. Narrowing it to
--     the firm in hand is a separate change to the manual-journal functions.
--   * The write policy as a second lock: a policy no role can reach decides nothing (migrations 499 and 513 carry none; 519
--     carries role-tier policies on its two declaration tables and none on the three client payroll tables, which is the
--     shape followed here).
--   * TRIGGER and REFERENCES are left as the platform's defaults have them: they are rights over the table's definition, which
--     PostgREST does not expose, and migrations 499, 513 and 519 leave them alone too (532 and 536 revoke them for the tables they
--     close, which is harmless and not needed here).
--
-- Idempotent. Reversible: 534_..._rollback.sql gives back INSERT, UPDATE and DELETE to `authenticated` and the default execute
-- right on `apb_apply_posted_line`, which RE-OPENS the hole. It restores what the migrations granted, which is not necessarily
-- what production held (the platform's default privileges may have given `anon` and `authenticated` more, TRUNCATE and a direct
-- EXECUTE among them): production's own ACL was not read, and the revoke here does not depend on it. The four maintenance
-- functions are not given back to anyone; 251 meant them for the service role.

DO $$
DECLARE
    r text;
    verb text;
    fn text;
BEGIN
    IF to_regclass('public.account_period_balances') IS NULL THEN
        RAISE NOTICE 'migration 534: public.account_period_balances does not exist; nothing to revoke';
        RETURN;
    END IF;

    REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.account_period_balances FROM PUBLIC, authenticated, anon;

    IF to_regprocedure('public.apb_apply_posted_line(uuid, uuid, uuid, date, bigint, bigint)') IS NOT NULL THEN
        REVOKE EXECUTE ON FUNCTION public.apb_apply_posted_line(uuid, uuid, uuid, date, bigint, bigint) FROM PUBLIC, authenticated, anon;
        GRANT EXECUTE ON FUNCTION public.apb_apply_posted_line(uuid, uuid, uuid, date, bigint, bigint) TO service_role;
    END IF;

    FOREACH fn IN ARRAY ARRAY['public.apb_rebuild_client(uuid, uuid)', 'public.apb_drifted_clients()',
                              'public.apb_rebuild_drifted()', 'public.apb_assert_no_drift()'] LOOP
        IF to_regprocedure(fn) IS NOT NULL THEN
            EXECUTE format('REVOKE EXECUTE ON FUNCTION %s FROM PUBLIC, authenticated, anon', fn);
        END IF;
    END LOOP;

    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
            IF has_table_privilege(r, 'public.account_period_balances', verb) THEN
                RAISE EXCEPTION 'migration 534: % still holds % on account_period_balances', r, verb;
            END IF;
        END LOOP;
        IF has_any_column_privilege(r, 'public.account_period_balances', 'INSERT')
           OR has_any_column_privilege(r, 'public.account_period_balances', 'UPDATE') THEN
            RAISE EXCEPTION 'migration 534: % still holds a column-level write privilege on account_period_balances', r;
        END IF;
        IF to_regprocedure('public.apb_apply_posted_line(uuid, uuid, uuid, date, bigint, bigint)') IS NOT NULL
           AND has_function_privilege(r, 'public.apb_apply_posted_line(uuid, uuid, uuid, date, bigint, bigint)', 'EXECUTE') THEN
            RAISE EXCEPTION 'migration 534: % can still execute apb_apply_posted_line', r;
        END IF;
        FOREACH fn IN ARRAY ARRAY['public.apb_rebuild_client(uuid, uuid)', 'public.apb_drifted_clients()',
                                  'public.apb_rebuild_drifted()', 'public.apb_assert_no_drift()'] LOOP
            IF to_regprocedure(fn) IS NOT NULL AND has_function_privilege(r, fn, 'EXECUTE') THEN
                RAISE EXCEPTION 'migration 534: % can still execute %', r, fn;
            END IF;
        END LOOP;
    END LOOP;

    IF to_regprocedure('public.apb_apply_posted_line(uuid, uuid, uuid, date, bigint, bigint)') IS NOT NULL
       AND NOT has_function_privilege('service_role', 'public.apb_apply_posted_line(uuid, uuid, uuid, date, bigint, bigint)', 'EXECUTE') THEN
        RAISE EXCEPTION 'migration 534: the service role cannot execute apb_apply_posted_line';
    END IF;

    IF NOT has_table_privilege('service_role', 'public.account_period_balances', 'INSERT')
       OR NOT has_table_privilege('service_role', 'public.account_period_balances', 'UPDATE')
       OR NOT has_table_privilege('service_role', 'public.account_period_balances', 'DELETE') THEN
        RAISE EXCEPTION 'migration 534: service_role lost a write privilege on account_period_balances';
    END IF;
END $$;
