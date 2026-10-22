-- Rollback of migration 534. RE-OPENS the hole: a signed-in session can write the monthly balances the reports read, and call
-- the function that applies a posted line to them.
DO $$
BEGIN
    IF to_regclass('public.account_period_balances') IS NOT NULL THEN
        GRANT INSERT, UPDATE, DELETE ON public.account_period_balances TO authenticated;
    END IF;
    IF to_regprocedure('public.apb_apply_posted_line(uuid, uuid, uuid, date, bigint, bigint)') IS NOT NULL THEN
        GRANT EXECUTE ON FUNCTION public.apb_apply_posted_line(uuid, uuid, uuid, date, bigint, bigint) TO PUBLIC;
    END IF;
END $$;
