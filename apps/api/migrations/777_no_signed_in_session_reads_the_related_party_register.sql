-- Migration 777: no signed-in session reads the related-party register (ledger POST-A-544, the database half).
--
-- WHAT WAS WRONG
--   `entities` holds a PAN, a GSTIN, a date of birth, a phone number and an address, and with `entity_relationships` and
--   `entity_to_entity_relationships` it is the firm's record of who stands behind which client. Since 21-11-2026 the SERVER shows
--   a member who is not firm-wide only the entities of their own clients (an entity is shown when it holds a role at one of
--   their clients, or no role at all). The DATABASE did not: the read policy on the three tables asks the firm and nothing
--   narrower, and `authenticated` held SELECT on all three, so a hand-made request to the database's own API by any member of
--   staff was answered with the whole register.
--
-- WHAT THIS DOES
--   REVOKES every privilege `authenticated`, `anon` and PUBLIC hold on the three tables (the writes went in migration 562; this
--   takes the read), checks the EFFECTIVE privilege (table level, column level, through PUBLIC), and that `service_role` kept
--   its own. The row policies stay as the second lock, as they do on every table closed this way.
--
--   A narrower read policy would have been the other answer, and it would have had to restate in SQL the server's rule of which
--   entity a member may see (roles at their clients, or no role at all), a second copy of a rule that already has one. The
--   browser reads none of the three (no `.from("<table>")` in `apps/web`), so taking the read away is the stronger lock and
--   leaves one definition.
--
-- DEPLOY ORDER: the API has read all three with its own client since the change merged as 40b2234d on 22-11-2026 (every
--   statement names the firm, held by `tests/test_the_register_and_a_time_entry_are_reached_through_the_servers_own_client.py`
--   over the whole server tree). This migration follows that deploy. An API still on the earlier code would be refused the
--   register with a permission error until it restarts; nothing is written by a read, so nothing is left half-done.
--
-- No row changes. Reversible: 777_no_signed_in_session_reads_the_related_party_register_rollback.sql.

DO $$
DECLARE
    tables text[] := ARRAY['entities', 'entity_relationships', 'entity_to_entity_relationships'];
    t text;
    r text;
    verb text;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('REVOKE ALL ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;

    FOREACH t IN ARRAY tables LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 777: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'SELECT')
               OR has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 777: % still holds a column-level privilege on %', r, t;
            END IF;
        END LOOP;
        IF NOT has_table_privilege('service_role', format('public.%I', t), 'SELECT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'INSERT')
           OR NOT has_table_privilege('service_role', format('public.%I', t), 'UPDATE') THEN
            RAISE EXCEPTION 'migration 777: service_role lost a privilege on %', t;
        END IF;
    END LOOP;
END $$;
