-- Migration 551: a signed-in session reads and writes none of the document tables and opens no stored file (POST-A-339, the document
-- group and Supabase Storage).
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- POST-A-010 (25-10-2026) moved every read and write of the document tables and of Supabase Storage out of the browser: the
-- Documents page, the vault, the portal page and the bank entry's attachment ask the API, and
-- `tests/test_a_sensitive_table_is_not_read_from_the_browser.py` holds that the browser names none of them. What that did not do
-- was take the grants and the policies away.
--
--   * `authenticated` still held SELECT, INSERT, UPDATE and DELETE on `documents`, `client_documents`, `document_requests`,
--     `document_extractions` and `document_risks` (and the platform's TRUNCATE on `authenticated` and `anon`), so a person with
--     their own sign-in could call PostgREST by hand and read, or write, exactly what the row policies let them: the register of
--     every document a client's papers are filed under, what the AI read out of them, and the risks it raised.
--   * The object policies of migrations 005, 426 and 469 on `storage.objects` let a signed-in session open, store and (a Partner)
--     remove a file under `{firm}/{client}/...` in the buckets `Documents` and `year-end-exports`, so a person with their own
--     sign-in could call Storage by hand and open any file of any client they are assigned to, with no route to ask whether the
--     person's per-person grid allowed it (the grid reached a stored year-end export and nothing else).
--
-- The API was moved first, in two changes that shipped and ran BEFORE this migration: POST-A-339 step 1 made every query it makes
-- on the document tables with its privileged client, naming the firm and the client the caller's role would have been limited to
-- (and `/health` reads `audit_actor: carried`), and the Storage step made every file it stores, signs or removes go through
-- `core/storage_door`, the SERVER's client bound to the folder the route asked about, with a rule over the source that no module
-- reads `.storage` of a client any other way. The old API against these changes fails soft and wrong (an empty list, a lookup that
-- says not found, a file that does not open), which is why they came first.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- 1. REVOKE SELECT, INSERT, UPDATE, DELETE and TRUNCATE from PUBLIC, `authenticated` and `anon` on the five document tables:
--
--      the register              documents, client_documents
--      what a client was asked   document_requests
--      what a model read         document_extractions, document_risks
--
--    (`entity_documents`, the sixth table of the family, holds no signed-in privilege already: migration 538 took them.) The
--    platform's REFERENCES and TRIGGER privileges are not privileges on rows and are left alone, as 499, 549 and 550 left them.
--    `service_role` keeps every privilege it had, and the migration REFUSES (rolls back) if it would be left without one. THE ROW
--    POLICIES STAY as the SECOND LOCK, the way 499, 549 and 550 left theirs.
--
-- 2. DROP the object policies a signed-in session was let in by: `documents_storage_select`, `documents_storage_insert`,
--    `documents_storage_delete`, `year_end_exports_storage_select`, `year_end_exports_storage_insert` and, if a database still
--    has one, `year_end_exports_storage_delete` (migration 426 made it and 469 dropped it, so neither production nor a database
--    built from the migrations has it; it is named so that a database that somehow kept it holds none either). The
--    SERVICE-ROLE policies of 204 and 426 stay, and are what the API's own key needs. Row security is on for `storage.objects`, so
--    with no policy for a signed-in role every Storage call that role makes finds no object and stores none: the privilege the
--    hosting platform grants on the table is not a lock that can be taken from here (`storage.objects` is the storage service's
--    own), and a table with row security on and no policy is how this platform says "nobody".
--
--    UNLIKE THE TABLES, THERE IS NO SECOND LOCK TO KEEP HERE: the object policies ARE the lock, so dropping them is the closure, and
--    the rollback re-creates them exactly. The three helper grants to `supabase_storage_admin` that 469 made (so the storage
--    service can evaluate those policies) are left in place: they are harmless without a policy that calls them, and revoking
--    them would be one more thing for the rollback to remember.
--
-- WHAT A SIGNED-IN SESSION NOW SEES
--   Any read or write of one of the five tables is "permission denied for table" (SQLSTATE 42501); any Storage call it makes on
--   `Documents` or `year-end-exports` finds nothing and stores nothing. A foreign-key cascade is not a privilege check, so deleting a
--   client still cascades. `firm-assets` is a PUBLIC bucket read by URL and was never behind a policy; the logo is written by the
--   server.
--
-- PRODUCTION, read from its catalogue on 26-10-2026: `authenticated` held SELECT, INSERT, UPDATE and DELETE (and REFERENCES, TRIGGER
-- and TRUNCATE) on the five tables, `anon` REFERENCES, TRIGGER and TRUNCATE; `storage.objects` carried eleven policies, five of them
-- the signed-in ones named above (no `year_end_exports_storage_delete`), all for the role `public` and so for every role, and six
-- the service-role ones; the buckets were `Documents` (private), `year-end-exports` (private) and `firm-assets` (public).

DO $$
DECLARE
    tables text[] := ARRAY[
        'documents', 'client_documents', 'document_requests', 'document_extractions', 'document_risks'
    ];
    policies text[] := ARRAY[
        'documents_storage_select', 'documents_storage_insert', 'documents_storage_delete',
        'year_end_exports_storage_select', 'year_end_exports_storage_insert', 'year_end_exports_storage_delete'
    ];
    t text;
    r text;
    p text;
    verb text;
    remaining record;
BEGIN
    FOREACH t IN ARRAY tables LOOP
        EXECUTE format('REVOKE SELECT, INSERT, UPDATE, DELETE, TRUNCATE ON public.%I FROM PUBLIC, authenticated, anon', t);
    END LOOP;
    FOREACH p IN ARRAY policies LOOP
        EXECUTE format('DROP POLICY IF EXISTS %I ON storage.objects', p);
    END LOOP;

    -- The check asks the EFFECTIVE privilege (has_table_privilege and has_any_column_privilege), which sees a privilege that
    -- reaches the role through PUBLIC, through membership of another role or at column level, none of which a look at
    -- information_schema.role_table_grants for the two role names would.
    FOREACH t IN ARRAY tables LOOP
        FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
            FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'] LOOP
                IF has_table_privilege(r, format('public.%I', t), verb) THEN
                    RAISE EXCEPTION 'migration 551: % still holds % on %', r, verb, t;
                END IF;
            END LOOP;
            IF has_any_column_privilege(r, format('public.%I', t), 'SELECT')
               OR has_any_column_privilege(r, format('public.%I', t), 'INSERT')
               OR has_any_column_privilege(r, format('public.%I', t), 'UPDATE') THEN
                RAISE EXCEPTION 'migration 551: % still holds a column-level privilege on %', r, t;
            END IF;
        END LOOP;
        -- The API is unaffected: the service role keeps what it had.
        FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE'] LOOP
            IF NOT has_table_privilege('service_role', format('public.%I', t), verb) THEN
                RAISE EXCEPTION 'migration 551: service_role no longer holds % on %', verb, t;
            END IF;
        END LOOP;
    END LOOP;

    -- Storage: with the signed-in policies gone, row security is what says "nobody" to a signed-in session, so the migration
    -- refuses (rolls back) if it is not on: a table with row security OFF and no policy is open to every role that holds a
    -- privilege on it, and the platform grants `authenticated` one. (Hosted Supabase has it on; the compat bootstrap of a
    -- throwaway database turns it on too.)
    IF NOT (SELECT relrowsecurity FROM pg_class WHERE oid = 'storage.objects'::regclass) THEN
        RAISE EXCEPTION 'migration 551: row security is off for storage.objects, so dropping its policies would open it to every role';
    END IF;
    -- Whatever is left on `storage.objects` may let in the service role and nobody else. A policy that does not name the service
    -- role is a way in for a signed-in session, whoever wrote it and whichever bucket it names, and one that names it beside an OR
    -- may be one too (`... OR auth.role() = 'service_role'` admits everyone its other limb does): the six that production holds
    -- (migrations 204 and 426) are all `bucket_id = '...' AND auth.role() = 'service_role'`. Refusing a harmless variant fails the
    -- migration visibly; passing a harmful one would not.
    FOR remaining IN
        SELECT policyname, coalesce(qual, '') || ' ' || coalesce(with_check, '') AS text
          FROM pg_policies WHERE schemaname = 'storage' AND tablename = 'objects'
    LOOP
        IF remaining.text NOT LIKE '%service_role%' OR remaining.text ~* '\mOR\M' THEN
            RAISE EXCEPTION 'migration 551: the policy % on storage.objects does not ask for the service role and nobody else', remaining.policyname;
        END IF;
    END LOOP;
END $$;
