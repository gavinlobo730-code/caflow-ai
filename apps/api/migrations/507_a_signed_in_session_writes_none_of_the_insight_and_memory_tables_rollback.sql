-- Rollback of migration 507: gives `authenticated` back the write privileges migrations 060, 095 and 320 granted on the insight
-- and memory tables. THIS RE-OPENS THE HOLE: any signed-in member of a firm can again change another member's insight status,
-- resolve a memory trigger, rewrite a client's compliance profile or plant an insight, trigger or year-end report directly
-- over PostgREST. Roll the API back FIRST (the repositories write with the privileged client and work either way, but the
-- firm filter on each write is code). It restores INSERT, UPDATE and DELETE as the earlier migrations granted them (INSERT
-- and SELECT alone on `client_profile_history` per 095, then the full set per 320, which is what a migration-built database
-- holds), and it does NOT restore the TRUNCATE privilege that 507 also revoked: no migration ever granted it.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['ai_insights', 'ai_memory_triggers', 'client_profiles', 'client_profile_history',
                             'firm_profiles', 'year_end_reports'] LOOP
        -- 070 stops part-way on a database built from scratch, so some of these are not there (see migration 507)
        CONTINUE WHEN to_regclass(format('public.%I', t)) IS NULL;
        EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
    END LOOP;
END $$;
