-- Rollback 366. Dropping the function returns reconcile_2b to its
-- statement-by-statement path, which is what the service still does whenever
-- `.rpc` is unavailable — so nothing breaks, and the interrupted-replace
-- window described in 366 comes back.
DROP FUNCTION IF EXISTS public.replace_gstr2b_reconciliation(UUID, UUID, TEXT, JSONB, JSONB);
