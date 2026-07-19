-- Migration 232: Schema-drift hotfix for production.
--
-- Two columns application code has referenced since Phase 1.2/3 without any
-- migration ever creating them — production reads/writes touching them have
-- been failing with "column does not exist" (masked behind generic
-- api_response(False, ...) error strings, so no crash, just a silently
-- broken feature).
--
-- 1. tasks.assignee_id — migration 113 already tried to index this column,
--    but no migration created it (only the legacy assigned_to FK exists).
--    Fixed at the source in 113 itself (adds the column before indexing),
--    but that fix only helps a FRESH install; this repeats it idempotently
--    so it also lands on the already-provisioned production database, which
--    ran past 113's position long ago and will not re-run it.
ALTER TABLE public.tasks
    ADD COLUMN IF NOT EXISTS assignee_id UUID REFERENCES public.team_members(id);

UPDATE public.tasks SET assignee_id = assigned_to
    WHERE assignee_id IS NULL AND assigned_to IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_assignee_id
    ON public.tasks (assignee_id)
    WHERE deleted_at IS NULL;

-- 2. tds_certificates.section — routers/tds_workspace.py's create_certificate
--    (IT Act §203, Form 16/16A draft generation) has always tried to persist
--    which TDS section (e.g. 194C) a certificate covers, but migration 037
--    never added the column, so every certificate-creation POST has been
--    failing. Unlike the other tds_workspace.py drift bugs (fixed by mapping
--    to the correct existing column), there is no existing equivalent column
--    to redirect this to, so it is added here.
ALTER TABLE public.tds_certificates
    ADD COLUMN IF NOT EXISTS section TEXT;
