-- Rollback for migration 640. Drops the index and takes the payroll keys off. The `tds_payable` key 640 took off the salary
-- TDS account is NOT put back: it was a mis-key that let the purchase bill's lookup credit a supplier's TDS to the salary
-- account, and every reader finds that account by its name without it.
BEGIN;
DROP INDEX IF EXISTS public.uq_chart_of_accounts_payroll_key;
UPDATE public.chart_of_accounts SET system_account_key = NULL WHERE system_account_key LIKE 'payroll\_%';
COMMIT;
