-- Rollback of migration 535. RE-OPENS the hole: any assigned member can rewrite or delete the record that a return was filed,
-- and with it lift the period lock that record enforces.
DO $$
BEGIN
    IF to_regclass('public.filings') IS NOT NULL THEN
        GRANT INSERT, UPDATE, DELETE ON public.filings TO authenticated;
    END IF;
END $$;
