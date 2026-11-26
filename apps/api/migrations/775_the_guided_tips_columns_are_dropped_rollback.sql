-- Rollback of migration 775: puts `users.guided_tips_on` and `users.guided_tips_seen` back as migration 774 declared them, empty. What each
-- person had chosen before the drop is not restored (it was dropped with the columns), and nothing reads either column since POST-A-538.
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS guided_tips_on BOOLEAN;
ALTER TABLE public.users ADD COLUMN IF NOT EXISTS guided_tips_seen TEXT[] NOT NULL DEFAULT '{}';
