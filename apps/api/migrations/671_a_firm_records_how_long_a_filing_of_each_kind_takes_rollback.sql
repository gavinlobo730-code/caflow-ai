-- Rollback of migration 671: DISCARDS every filing-effort estimate a firm recorded. The capacity forecast then counts obligations not
-- worked as a task as items without an estimate again, which is what it did before. Roll the code back with this file: the workload
-- router and the capacity service name the table.

BEGIN;

DROP TABLE IF EXISTS public.compliance_effort_estimates;

COMMIT;
