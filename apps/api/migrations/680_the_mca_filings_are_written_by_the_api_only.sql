-- Migration 680: the MCA filings are written by the API only (ledger POST-A-442).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Migrations 012 and 041 granted `authenticated` SELECT, INSERT, UPDATE and DELETE on `mca_filings`, and migrations 260, 415, 493 and 540 put
-- row policies and a trigger behind the writes (the firm, the client assignment, the `mca` tier, an approver for a filing recorded as filed, and
-- a Partner to clear a filing's client). The browser wrote the table until the firm-level Add Filing moved onto `POST /api/mca-workspace/filings`
-- (POST-A-442, part 1, 16-11-2026), and since then nothing in `apps/web` writes it: it reads the table on the firm-level MCA screen only. The
-- grant was left to a hand-made PostgREST request from a signed-in session, which could record a filing with no category, no audit event, no
-- check that its company belongs to its client, and no closing of the compliance obligation the route performs.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's two writers (`routers/mca_workspace.create_filing` and `update_filing_status`) write with the privileged client, naming the firm and
-- the client, since part 1. This migration REVOKES INSERT, UPDATE, DELETE and TRUNCATE on `mca_filings` from `authenticated`, `anon` and PUBLIC
-- and checks the EFFECTIVE privilege (table level, column level, through PUBLIC) and that `service_role` kept its writes. Reading and the row
-- policies are untouched, so a member still reads the filings of the clients they are assigned to, and the policies stay as the second lock.
--
-- DEPLOY ORDER: part 1 must be live in production at least an hour before this applies, because an API instance still writing with the
-- caller's own sign-in would answer "permission denied" to a CA adding a filing.
--
-- Idempotent. Reversible: 680_..._rollback.sql restores the verbs migrations 012 and 041 granted.

DO $$
DECLARE
    t text := 'mca_filings';
    r text;
    verb text;
BEGIN
    IF to_regclass(format('public.%I', t)) IS NULL THEN
        RETURN;
    END IF;
    EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
            IF has_table_privilege(r, format('public.%I', t), verb) THEN
                RAISE EXCEPTION 'migration 680: % still holds % on %', r, verb, t;
            END IF;
        END LOOP;
        IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
           OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
            RAISE EXCEPTION 'migration 680: % still holds a column-level write privilege on %', r, t;
        END IF;
    END LOOP;
    IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
       OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
       OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
        RAISE EXCEPTION 'migration 680: service_role lost its write on %', t;
    END IF;
END $$;
