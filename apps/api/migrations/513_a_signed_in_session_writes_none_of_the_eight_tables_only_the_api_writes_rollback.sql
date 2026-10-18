-- Rollback of migration 513: gives `authenticated` back the write verbs production held on the eight tables on 18-10-2026.
-- (TRUNCATE is not given back: a platform default PostgREST does not expose.) Roll the API back first only if it was changed to
-- depend on the revoke; the privileged writes work either side.
GRANT INSERT, UPDATE, DELETE ON public.credit_note_allocations, public.user_capacity, public.task_tags,
    public.task_dependencies TO authenticated;
GRANT INSERT, UPDATE ON public.invoice_sequences TO authenticated;
GRANT INSERT ON public.task_timeline_events TO authenticated;
