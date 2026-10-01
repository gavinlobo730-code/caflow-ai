-- Rollback for 451. DISCARDS every billing rate recorded since it landed: each
-- person's default and each engagement's override. Time entries keep the rate they
-- were STORED with (`time_entries.billable_rate_paise` is migration 073's column and
-- is not touched), so work already logged is not re-priced by this.
--
-- Roll the code back with this file: `billing_service.unbilled_work` calls
-- `unbilled_time_summary` and the staff-rate and engagement-rate endpoints write the
-- two dropped columns, so each fails on its first call without them.

BEGIN;

DROP FUNCTION IF EXISTS public.unbilled_time_summary(uuid, uuid);

ALTER TABLE public.fee_engagements
    DROP CONSTRAINT IF EXISTS fee_engagements_billable_rate_paise_check;
ALTER TABLE public.fee_engagements DROP COLUMN IF EXISTS billable_rate_paise;

ALTER TABLE public.users
    DROP CONSTRAINT IF EXISTS users_default_billable_rate_paise_check;
ALTER TABLE public.users DROP COLUMN IF EXISTS default_billable_rate_paise;

COMMIT;
