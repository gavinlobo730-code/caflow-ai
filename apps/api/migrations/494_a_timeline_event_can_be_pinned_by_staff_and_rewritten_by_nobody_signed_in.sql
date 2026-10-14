-- Migration 494 — a timeline event can be pinned by staff and rewritten by nobody signed in
-- (found by the 14-10-2026 audit of the browser's direct writes; ledger POST-A-228).
--
-- WHAT THE AUDIT SAW, AND WHAT PRODUCTION ACTUALLY HAS
--   Migration 045 granted `authenticated` SELECT, INSERT and UPDATE on `client_timeline_events`; migration 056 then granted
--   SELECT and never revoked the rest. A database BUILT FROM THESE MIGRATIONS therefore lets any staff role that passes the
--   Reviewer-and-above row policy update EVERY column of an event (title, description, the actor fields, `deleted_at`),
--   which is how the access matrix and the audit read it. PRODUCTION DOES NOT HAVE THAT GRANT: read from its catalogue on
--   14-10-2026, `authenticated` holds INSERT and SELECT on the table and no UPDATE at all, at table or column level (the
--   comment in core/permissions.py, "no UPDATE or DELETE grant", is true of production and false of a migration-built
--   database). Production's grant was changed outside the migrations, and this repository's database drifted from it.
--
--   The same drift hides a broken feature. The client timeline's pin button (components/ClientTimeline.tsx) updates
--   `is_pinned` with the caller's own sign-in and ignored the answer, so in production every pin was refused with
--   "permission denied" and the screen showed it pinned anyway; the next load put it back.
--
-- WHAT THIS DOES
--   * REVOKE UPDATE (table level) from `authenticated`: a no-op in production, and it makes a migration-built database
--     match production, so the access matrix measures the same thing production is.
--   * GRANT UPDATE (is_pinned) alone: staff (Reviewer and above, by the existing row policy) can pin and unpin an event, the
--     one write the screen makes, and cannot change what an event says, who it names or whether it is deleted. A row
--     policy cannot restrict columns; a column grant can.
--   Inserts are untouched. The activity feed is not the audit log (`audit_log` is separate and append-only).
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * The browser still INSERTS events with an actor it names itself (lib/services/timeline.ts). Moving that behind a
--     server door that sets the actor is a separate piece of work (ledger POST-A-228 keeps it).
--   * The service role is untouched (the API writes events through it).
--
-- Idempotent. Reversible: 494_..._rollback.sql restores the table-level UPDATE grant, which re-creates the drift.

REVOKE UPDATE ON public.client_timeline_events FROM authenticated;
GRANT UPDATE (is_pinned) ON public.client_timeline_events TO authenticated;

DO $$
BEGIN
  IF has_table_privilege('authenticated', 'public.client_timeline_events', 'UPDATE') THEN
    RAISE EXCEPTION 'migration 494: authenticated still holds a table-level UPDATE on client_timeline_events';
  END IF;
  IF NOT has_column_privilege('authenticated', 'public.client_timeline_events', 'is_pinned', 'UPDATE') THEN
    RAISE EXCEPTION 'migration 494: authenticated cannot update is_pinned';
  END IF;
  IF has_column_privilege('authenticated', 'public.client_timeline_events', 'title', 'UPDATE')
     OR has_column_privilege('authenticated', 'public.client_timeline_events', 'deleted_at', 'UPDATE') THEN
    RAISE EXCEPTION 'migration 494: authenticated can still rewrite an event';
  END IF;
END $$;
