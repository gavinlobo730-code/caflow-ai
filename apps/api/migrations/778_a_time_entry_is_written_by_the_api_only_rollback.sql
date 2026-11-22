-- Rollback of migration 778: gives `authenticated` back INSERT, UPDATE and DELETE on `time_entries` (TRUNCATE is not given back:
-- a platform default the database's own API does not expose). A hand-made request can then mark, re-price or remove any entry of
-- the firm again, which is what POST-A-546 closed. The API's own writes work either side.
DO $$
BEGIN
    IF to_regclass('public.time_entries') IS NOT NULL THEN
        GRANT INSERT, UPDATE, DELETE ON public.time_entries TO authenticated;
    END IF;
END $$;
