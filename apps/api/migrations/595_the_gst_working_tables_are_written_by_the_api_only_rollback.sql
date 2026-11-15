-- Rollback of migration 595: gives `authenticated` back the write verbs production held on the seven GST working tables on 15-11-2026 (INSERT,
-- UPDATE and DELETE; the row policies still decide which rows). TRUNCATE is not given back: a platform default PostgREST does not expose. The
-- API's privileged writes work either side.
DO $$
DECLARE
    t text;
BEGIN
    FOREACH t IN ARRAY ARRAY['itc_reversal_register', 'gstr2b_uploads', 'gst_sync_jobs', 'gst_portal_snapshots', 'client_gst_turnover', 'hsn_sac_preferences', 'gst_challans'] LOOP
        IF to_regclass(format('public.%I', t)) IS NOT NULL THEN
            EXECUTE format('GRANT INSERT, UPDATE, DELETE ON public.%I TO authenticated', t);
        END IF;
    END LOOP;
END $$;
