-- Rollback of migration 586: drop the time summary function. Nothing else was changed, so nothing else is undone. Safe to run twice.

DROP FUNCTION IF EXISTS public.time_entry_summary(uuid, uuid, timestamptz, timestamptz);
