-- Rollback of migration 616: drop the function. The s.16(4) radar then reads every bill of the window's reconciled months and runs the
-- s.16(2)(aa) pass over all of them in Python, as it did before (the service falls back when the call fails).
BEGIN;
DROP FUNCTION IF EXISTS public.itc_time_bar_candidates(uuid, uuid, date, date, text[]);
COMMIT;
