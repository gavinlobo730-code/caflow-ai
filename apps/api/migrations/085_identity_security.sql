-- PracticeSync AI — Migration 085: Identity security (sessions, login history)
-- Final pre-trial milestone (M6). Supports:
--   * Immediate session revocation / forced logout (users.sessions_revoked_at):
--     auth rejects any JWT whose iat predates this timestamp.
--   * Login history / administrative login audit (login_events).
-- Additive, idempotent, reversible.

ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS sessions_revoked_at TIMESTAMPTZ;
COMMENT ON COLUMN public.users.sessions_revoked_at IS
  'M6: any access token issued (iat) before this instant is rejected by get_current_user — powers force-logout / global logout / suspend.';

CREATE TABLE IF NOT EXISTS public.login_events (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id     UUID,
  user_id     UUID,
  email       TEXT,
  event       TEXT NOT NULL CHECK (event IN ('login', 'logout', 'failed_login', 'forced_logout', 'suspended')),
  ip          TEXT,
  user_agent  TEXT,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_login_events_firm_created ON public.login_events(firm_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_login_events_user        ON public.login_events(user_id, created_at DESC);

ALTER TABLE public.login_events ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "login_events_partner_read" ON public.login_events;
CREATE POLICY "login_events_partner_read" ON public.login_events
  FOR SELECT TO authenticated
  USING (firm_id = public.get_my_firm_id() AND public.get_my_role() = 'Partner');

GRANT SELECT ON public.login_events TO authenticated;
GRANT ALL    ON public.login_events TO service_role;

COMMENT ON TABLE public.login_events IS
  'M6: login / logout / failed-login / forced-logout audit trail (Partner-readable; written via service role).';
