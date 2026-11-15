-- Rollback of migration 605: gives `authenticated` back the write verbs production held on the three online-payment tables on 15-11-2026 (INSERT, UPDATE and
-- DELETE; the row policies still decide which rows). TRUNCATE is not given back: a platform default PostgREST does not expose. The API's
-- privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['customer_payment_links', 'customer_payments', 'customer_payment_events'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
