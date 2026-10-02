-- Rollback for 471. DISCARDS every scheduler claim row.
--
-- The claims are locks, not records: scheduler_runs is the history and is not
-- touched. Dropping them while the code is still deployed is safe in one
-- direction only. The API treats a MISSING claim function as "this database has
-- not got the migration" and runs the sweep the way it did before 471 (the
-- select-then-run check, with a loud log line), so the daily jobs keep running —
-- but the two-instances guarantee is gone for as long as the functions are. Roll
-- the code back with this file if a second instance is running.

BEGIN;

DROP FUNCTION IF EXISTS public.prune_scheduler_claims(integer);
DROP FUNCTION IF EXISTS public.finish_scheduler_claim(uuid, text, text);
DROP FUNCTION IF EXISTS public.renew_scheduler_claim(uuid, text, integer);
DROP FUNCTION IF EXISTS public.claim_scheduler_job(text, date, uuid, text, text, integer, boolean, integer);
DROP TABLE IF EXISTS public.scheduler_claims;

COMMIT;
