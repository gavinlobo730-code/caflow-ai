-- Rollback of migration 680: gives `authenticated` back the write verbs migrations 012 and 041 granted on `mca_filings` (INSERT, UPDATE and
-- DELETE; the policies of migrations 260, 415, 493 and 540 still decide which rows). TRUNCATE is not given back: a platform default PostgREST
-- does not expose. The API's privileged writes work either side.
DO $$
BEGIN
    IF to_regclass('public.mca_filings') IS NOT NULL THEN
        GRANT INSERT, UPDATE, DELETE ON public.mca_filings TO authenticated;
    END IF;
END $$;
