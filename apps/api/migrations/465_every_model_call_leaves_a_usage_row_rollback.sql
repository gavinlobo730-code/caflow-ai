-- Rollback for 465. DISCARDS every recorded model-call usage row.
--
-- Nothing else reads the table yet (the per-firm budget and the Partner usage
-- screen are later work), and domain/ai/gateway swallows a failed insert, so the
-- gateway keeps working with this table gone — it logs the attempt and carries on.
-- Roll the code back with this file if you want the rows not to be attempted.

BEGIN;

DROP TABLE IF EXISTS public.ai_usage_events;

COMMIT;
