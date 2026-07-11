-- Migration 187: add the columns timeline_service.py has always written but
-- the live client_timeline_events table never had.
--
-- Migration 045 (timeline_foundation) defines a rich schema (event_type,
-- entity_type/entity_id, actor_*, amount_paise, action_label/action_url,
-- visibility, is_pinned, period, deleted_by), and services/timeline_service.py
-- has always built its insert payload against exactly that schema — but the
-- LIVE table only ever had a much smaller column set (id, firm_id, client_id,
-- category, severity, title, description, financial_year, metadata,
-- created_by, created_at, updated_at, deleted_at), never matching migration
-- 045's design. Every log_timeline_event() call has therefore failed on
-- "column does not exist" since this table was created — confirmed live: 0
-- rows exist despite every sales invoice, receipt, credit note, etc. across
-- this whole app calling it on every create/issue/cancel. The write is
-- wrapped in a non-fatal try/except (by design, matching audit_service.py's
-- contract), so this has never broken anything else — it has just silently
-- meant the "Timeline" / client activity feed feature has never actually
-- recorded a single event.
--
-- Column types: entity_id/actor_id are TEXT, not UUID (migration 045's
-- original types) — matching client_id, which migration 074 already
-- deliberately made TEXT on this table ("client_timeline_events, whose
-- client_id is TEXT"), so a non-UUID actor/entity id can never break an
-- insert the way a strict UUID column would. category/severity are already
-- live as plain TEXT (not migration 045's enum types), so the new columns
-- follow that same plain-TEXT convention for consistency rather than
-- introducing enum types the rest of the table doesn't use.

-- Separately: `authenticated` (the role the backend's Supabase client uses
-- for these calls — same finding as migration 186) had SELECT only on this
-- table, no INSERT — confirmed live: `INSERT ... AS authenticated` fails
-- with "permission denied for table client_timeline_events" even with the
-- columns above in place. routers/timeline.py's only endpoint is a read
-- (list_timeline_events); the only write is timeline_service.py's insert.

ALTER TABLE client_timeline_events
  ADD COLUMN IF NOT EXISTS period TEXT,
  ADD COLUMN IF NOT EXISTS event_type TEXT,
  ADD COLUMN IF NOT EXISTS action_label TEXT,
  ADD COLUMN IF NOT EXISTS action_url TEXT,
  ADD COLUMN IF NOT EXISTS entity_type TEXT,
  ADD COLUMN IF NOT EXISTS entity_id TEXT,
  ADD COLUMN IF NOT EXISTS actor_type TEXT,
  ADD COLUMN IF NOT EXISTS actor_id TEXT,
  ADD COLUMN IF NOT EXISTS actor_name TEXT,
  ADD COLUMN IF NOT EXISTS amount_paise BIGINT,
  ADD COLUMN IF NOT EXISTS is_pinned BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS visibility TEXT NOT NULL DEFAULT 'all',
  ADD COLUMN IF NOT EXISTS deleted_by TEXT;

CREATE INDEX IF NOT EXISTS idx_client_timeline_events_entity
  ON client_timeline_events (entity_type, entity_id)
  WHERE entity_id IS NOT NULL;

GRANT INSERT ON client_timeline_events TO authenticated;
