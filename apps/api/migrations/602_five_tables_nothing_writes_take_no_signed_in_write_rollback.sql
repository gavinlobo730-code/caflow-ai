-- Rollback of migration 602: gives `authenticated` back the write verbs production held on the five tables nothing writes on
-- 15-11-2026 (INSERT, UPDATE and DELETE; the row policies still decide which rows). TRUNCATE is not given back: a platform default PostgREST
-- does not expose. Nothing writes them either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['msme_payments', 'msme_vendors', 'retainer_clients', 'suppliers', 'ledger_balances'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
