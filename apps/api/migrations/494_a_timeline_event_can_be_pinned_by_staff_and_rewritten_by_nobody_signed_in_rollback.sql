-- Rollback of migration 494: restores the table-level UPDATE grant migration 045 gave and production does not have.
-- THIS RE-OPENS THE DRIFT: on a migration-built database any staff role at Reviewer or above can rewrite an event.
REVOKE UPDATE (is_pinned) ON public.client_timeline_events FROM authenticated;
GRANT UPDATE ON public.client_timeline_events TO authenticated;
