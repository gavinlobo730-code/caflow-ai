-- Rollback for 408. A read-only reporting function: dropping it removes the
-- stock ageing report and destroys no data.

DROP FUNCTION IF EXISTS public.stock_ageing_as_at(uuid, uuid, date, uuid);
