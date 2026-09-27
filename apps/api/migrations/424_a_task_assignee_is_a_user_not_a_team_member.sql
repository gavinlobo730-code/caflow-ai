-- 424: tasks.assignee_id / assigned_to point at a table nothing writes.
--
-- WHY
--   Both tasks_assignee_id_fkey and tasks_assigned_to_fkey reference
--   public.team_members(id) -- a table that has held ZERO rows in production
--   since it was created (001_initial_schema.sql). Every other reader of "who
--   is on the firm's team" -- lib/data/tasks.ts's own getTeamMembers(),
--   task_service.py's compute_team_workload, and the fix that
--   document_intelligence_v2.py's own comment records for an unrelated bug
--   ("`team_members` has no user_id column at all... `users` is the table
--   this has to read") -- already treats public.users as the team roster.
--   Nothing in this codebase writes public.team_members at all.
--
--   So the app/tasks 'New Task' modal's Assign To dropdown is correctly
--   populated from users.id (via getTeamMembers()), and every submission
--   fails: leaving it at the default sends assignee_id:"" (22P02, invalid
--   UUID), and picking the one real option sends a genuine users.id that
--   satisfies no row of team_members (23503, tasks_assignee_id_fkey). No task
--   has ever been created via this modal in production, confirmed by both
--   columns holding zero non-null values on every existing row.
--
-- WHAT THIS DOES
--   Repoints both FKs at public.users(id), the table every other reader
--   already assumes. Safe to add outright: zero rows on either column today,
--   so nothing already stored could fail the new constraint -- but NOT VALID
--   + VALIDATE is used anyway, matching migration 315's reasoning, because
--   this runs unattended on merge and a pattern that is correct whether or
--   not the table already held data is worth more than one that only
--   happens to be correct today. team_members itself is left in place --
--   dropping it is a separate decision or the docs/schema-drift.md refresh.

BEGIN;

ALTER TABLE public.tasks
    DROP CONSTRAINT IF EXISTS tasks_assignee_id_fkey;

ALTER TABLE public.tasks
    ADD CONSTRAINT tasks_assignee_id_fkey
    FOREIGN KEY (assignee_id) REFERENCES public.users(id)
    NOT VALID;

ALTER TABLE public.tasks
    VALIDATE CONSTRAINT tasks_assignee_id_fkey;

ALTER TABLE public.tasks
    DROP CONSTRAINT IF EXISTS tasks_assigned_to_fkey;

ALTER TABLE public.tasks
    ADD CONSTRAINT tasks_assigned_to_fkey
    FOREIGN KEY (assigned_to) REFERENCES public.users(id)
    NOT VALID;

ALTER TABLE public.tasks
    VALIDATE CONSTRAINT tasks_assigned_to_fkey;

COMMENT ON COLUMN public.tasks.assignee_id IS
    'public.users.id -- the firm team member a task is assigned to. '
    'Migration 424 repointed this from the always-empty public.team_members.';

COMMENT ON COLUMN public.tasks.assigned_to IS
    'public.users.id -- same population as assignee_id (see lib/data/tasks.ts, '
    'which ORs the two). Migration 424 repointed this from public.team_members.';

COMMIT;
