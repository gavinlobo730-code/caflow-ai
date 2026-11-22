-- Rollback of migration 777: gives `authenticated` back the SELECT it held on the three register tables before it (the writes were
-- taken by migration 562 and are not given back here). The row policies were never changed, so the read is the firm's again: any
-- member of staff reads the whole register over the database's own API, which is what POST-A-544 closed. The API's own reads work
-- either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['entities', 'entity_relationships', 'entity_to_entity_relationships'] LOOP
        IF to_regclass(format('public.%I', t)) IS NULL THEN
            CONTINUE;
        END IF;
        EXECUTE format('GRANT SELECT ON public.%I TO authenticated', t);
    END LOOP;
END $$;
