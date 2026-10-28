-- Rollback of migration 555: drops `users.first_run_dismissed_at`. Every person who dismissed the first-run checklist sees it again
-- (until their firm has done its first four things); nothing else reads the column.
ALTER TABLE public.users DROP COLUMN IF EXISTS first_run_dismissed_at;
