-- Migration 595: the GST working tables are written by the API only (ledger POST-A-008, the GST tranche, part 2 of 2).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Seven GST tables are granted to the signed-in role behind policies that ask the firm and the client assignment (and, on three, that the
-- firm's own practice is a Partner's) and no role tier: `itc_reversal_register` (the reversals that feed GSTR-3B Table 4(B)), `gstr2b_uploads`,
-- `gst_sync_jobs`, `gst_portal_snapshots`, `client_gst_turnover` (the turnover that decides whether an IRN is owed), `hsn_sac_preferences`, and
-- `gst_challans`, which nothing reads or writes (no row in production). Production granted `authenticated` INSERT, UPDATE, DELETE and TRUNCATE on
-- all seven and `anon` TRUNCATE (read on 15-11-2026). The browser writes none of them, so a hand-made PostgREST request from a signed-in session
-- was the only user of the grant, and a Reviewer assigned to a client, who writes nothing through the API, could write a reversal into the
-- register that feeds the return. Found through POST-A-008's list of the tables a signed-in session reaches outside the access matrix.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- The API's writers moved onto the privileged client first (part 1, held over the source by
-- `tests/test_the_gst_working_tables_are_written_with_the_privileged_client.py`). This migration then REVOKES INSERT, UPDATE, DELETE and TRUNCATE
-- on the seven tables from `authenticated`, `anon` and PUBLIC and checks the EFFECTIVE privilege (table level, column level, through PUBLIC) and
-- that `service_role` kept its writes. Reading and the row policies are untouched, so a member still reads the rows of the clients they are
-- assigned to. The shape is migration 593's.
--
-- DEPLOY ORDER: part 1 reached production first and this ships at least an hour after it, because an API instance still serving when the grant
-- goes, writing with the caller's own sign-in, would answer "permission denied" to a CA recording a reversal or uploading a 2B file.
--
-- Idempotent. Reversible: 595_..._rollback.sql restores the verbs production held.

DO $$
DECLARE
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY ARRAY['itc_reversal_register', 'gstr2b_uploads', 'gst_sync_jobs', 'gst_portal_snapshots', 'client_gst_turnover', 'hsn_sac_preferences', 'gst_challans'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);

        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 595: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 595: % still holds a column-level write privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'DELETE') THEN
            RAISE EXCEPTION 'migration 595: service_role lost its write on %', t;
        END IF;
    END LOOP;
END $$;
