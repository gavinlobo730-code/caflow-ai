-- Rollback of migration 600: gives `authenticated` back the write verbs production held on the six recurring and billing tables on
-- 15-11-2026 (INSERT, UPDATE and DELETE; the row policies still decide which rows). TRUNCATE is not given back: a platform default PostgREST
-- does not expose. The API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['billing_schedules', 'recurring_invoice_template_lines', 'recurring_purchase_bill_template_lines', 'recurring_invoice_runs', 'recurring_purchase_bill_runs', 'recurring_journal_runs'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
