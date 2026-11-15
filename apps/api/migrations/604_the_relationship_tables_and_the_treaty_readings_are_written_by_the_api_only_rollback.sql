-- Rollback of migration 604: gives `authenticated` back the write verbs production held on the seven tables on 15-11-2026 (INSERT, UPDATE and
-- DELETE; the row policies still decide which rows). TRUNCATE is not given back: a platform default PostgREST does not expose. The API's
-- privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['entity_roles', 'properties', 'related_party_loans', 'dtaa_treaty_rates', 'entity_client_links',
                             'auto_journal_suggestions', 'engagement_letters'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
