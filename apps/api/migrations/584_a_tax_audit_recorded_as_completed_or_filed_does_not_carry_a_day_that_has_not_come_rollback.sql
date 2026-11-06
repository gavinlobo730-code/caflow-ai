-- Rollback of migration 584: drops the trigger and its function, which RE-OPENS the gap (a tax audit recorded as completed or filed may carry a day that has not come).
BEGIN;

SELECT set_config('lock_timeout', '15s', true);

DROP TRIGGER IF EXISTS tax_audit_dates_follow_the_status ON public.tax_audits;
DROP FUNCTION IF EXISTS public.tax_audit_dates_follow_the_status();

COMMIT;
