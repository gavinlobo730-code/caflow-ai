-- Migration 609: the engagement letters are written by the API only (ledger POST-A-008, the engagements tranche, part 2 of 2).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- `engagements` (an engagement letter: the fee, the scope of work, the signatory and the signing link of a client, or of a lead before there is
-- one) is granted to the signed-in role behind policies that ask the firm, the client assignment, the practice's own client and the client
-- write tier (migrations 529 and 537). Production granted `authenticated` INSERT, UPDATE, DELETE and TRUNCATE and `anon` TRUNCATE (read on
-- 15-11-2026). The browser writes none of it, and no database function does, so a hand-made PostgREST request from a signed-in session was the
-- only user of the grant: a member with the write tier could rewrite a letter's fee or its signing link straight over PostgREST, with none of
-- the checks the routes make (a letter's state, its number, its audit event). It is the last table on POST-A-008's list of the tables a
-- signed-in session reaches outside the access matrix that such a session could write.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (part 1, held over the source by
-- `tests/test_the_engagement_letters_are_written_with_the_privileged_client.py`), each route asking what the policies asked, and the link of a
-- signed letter to the client a lead becomes asking the caller's reach of both clients itself. This migration then REVOKES INSERT, UPDATE,
-- DELETE and TRUNCATE on the table from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column level,
-- through PUBLIC) and that `service_role` kept its writes. Reading, the row policies and the trigger that stops a member clearing a letter's
-- client (537) are untouched. The shape is migration 593's.
--
-- DEPLOY ORDER: part 1 reached production first and this ships at least an hour after it, because an API instance still serving when the grant
-- goes, writing with the caller's own sign-in, would answer "permission denied" to a CA sending or signing a letter.
--
-- Idempotent. Reversible: 609_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['engagements'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 609: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 609: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 609: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
