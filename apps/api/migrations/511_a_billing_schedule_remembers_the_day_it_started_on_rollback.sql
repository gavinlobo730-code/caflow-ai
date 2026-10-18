-- Rollback of migration 511: drops the anchor date. Schedules go back to being measured from their next run date, which is
-- the behaviour migration 511 replaced (month ends then step from the previous run date). Roll the API back FIRST: the
-- deployed API writes this column on create and on a next-run-date edit.
ALTER TABLE public.billing_schedules DROP COLUMN IF EXISTS anchor_date;
