-- Rollback of migration 597: gives `authenticated` back the write verbs production held on the accounting and year-end working tables on
-- 15-11-2026 (INSERT, UPDATE and DELETE; the row policies still decide which rows), on each of the nine that exists. TRUNCATE is not given
-- back: a platform default PostgREST does not expose. The API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['schedule_iii_ratio_explanations', 'schedule_iii_ratio_inputs', 'schedule_iii_unbilled_reviews', 'account_budgets', 'cost_centres', 'year_end_checklist_items', 'year_end_checklists', 'year_end_reviews', 'notes_to_accounts'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
