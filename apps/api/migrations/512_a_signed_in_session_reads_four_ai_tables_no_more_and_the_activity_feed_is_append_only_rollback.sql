-- Rollback of migration 512.
--
-- Restores the four AI tables' privileges as migration 505 left them (SELECT, REFERENCES and TRIGGER to `authenticated`;
-- REFERENCES and TRIGGER to `anon`, which held no SELECT) and drops the append-only trigger. TRUNCATE on `client_timeline_events` is NOT given back: no code path needs it
-- and it was a platform default, not a migration's grant. Roll the API back FIRST: the deployed API reads `ai_summaries` with
-- the privileged client, which works either side of this file.

GRANT SELECT, REFERENCES, TRIGGER ON public.ai_context_windows, public.ai_summaries, public.ai_feedback, public.ai_actions
    TO authenticated;
GRANT REFERENCES, TRIGGER ON public.ai_context_windows, public.ai_summaries, public.ai_feedback, public.ai_actions
    TO anon;

DROP TRIGGER IF EXISTS client_timeline_events_append_only ON public.client_timeline_events;
DROP FUNCTION IF EXISTS public.client_timeline_events_append_only();
