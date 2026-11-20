-- Rollback of migration 774: drops `users.guided_tips_on` and `users.guided_tips_seen`. Every person is back on the default (tips on) and sees
-- every tip again; nothing else reads either column.
ALTER TABLE public.users DROP COLUMN IF EXISTS guided_tips_seen;
ALTER TABLE public.users DROP COLUMN IF EXISTS guided_tips_on;
