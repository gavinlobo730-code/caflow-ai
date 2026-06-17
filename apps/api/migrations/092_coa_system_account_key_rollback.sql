-- Rollback for Migration 092: chart_of_accounts.system_account_key
-- Removes the reporting control-account key. The cash-basis resolver then
-- falls back to name matching. No financial data is affected.

DROP INDEX IF EXISTS idx_chart_of_accounts_system_key;
ALTER TABLE chart_of_accounts DROP COLUMN IF EXISTS system_account_key;
