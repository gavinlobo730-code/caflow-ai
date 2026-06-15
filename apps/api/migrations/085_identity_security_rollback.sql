-- Rollback for 085_identity_security.sql
DROP POLICY IF EXISTS "login_events_partner_read" ON public.login_events;
DROP TABLE IF EXISTS public.login_events;
ALTER TABLE public.users DROP COLUMN IF EXISTS sessions_revoked_at;
