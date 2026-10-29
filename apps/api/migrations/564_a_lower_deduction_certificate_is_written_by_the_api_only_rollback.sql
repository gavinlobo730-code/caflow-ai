-- Rollback of migration 564: gives `authenticated` back the write verbs production held on `tds_lower_deduction_certificates` on
-- 29-10-2026 (INSERT, UPDATE and DELETE). TRUNCATE is not given back: a platform default PostgREST does not expose. The API's
-- privileged writes work either side.
DO $$
BEGIN
    IF to_regclass('public.tds_lower_deduction_certificates') IS NOT NULL THEN
        GRANT INSERT, UPDATE, DELETE ON public.tds_lower_deduction_certificates TO authenticated;
    END IF;
END $$;
