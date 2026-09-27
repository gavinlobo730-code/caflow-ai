-- 429: an engagement's standard checklist item exists once.
--
-- WHY
--   GET /api/year-end/{id}/checklist seeds the twelve standard items the first
--   time an engagement's checklist is read (routers/year_end_checklist.py). It
--   was read-then-insert with nothing to stop two first reads racing, and from
--   this change the year-end DASHBOARD — the default tab — reads it too, beside
--   the Checklist tab: open the engagement and click Checklist quickly (or run
--   React's dev strict mode) and both reads find nothing and both seed, leaving
--   24 items and a completion count that can never reach 100%.
--
--   Measured on 28-09-2026: no (engagement_id, item_code) is duplicated in
--   production, so the index can be created outright.
--
-- WHAT THIS DOES
--   A unique index on (engagement_id, item_code), which the seed now targets
--   with ON CONFLICT DO NOTHING (upsert with ignore_duplicates) and re-reads.

BEGIN;

CREATE UNIQUE INDEX IF NOT EXISTS year_end_checklist_items_engagement_item_code_key
    ON public.year_end_checklist_items (engagement_id, item_code);

COMMIT;
