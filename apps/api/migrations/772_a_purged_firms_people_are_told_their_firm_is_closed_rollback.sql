-- Rollback of migration 772 (POST-A-499). Drops the markers. A person whose firm was purged before the rollback is again sent to the new-practice
-- wizard by a session that predates the purge, as they were before the migration.
BEGIN;
DROP TABLE IF EXISTS public.closed_account_markers;
COMMIT;
