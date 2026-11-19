-- Migration 765 (POST-A-486): a login says which devices it is signed in on.
--
-- The owner decided on 18-11-2026 that one login may be used on any number of devices (no cap), and that the product must be able to
-- tell them apart and say so. Until now `login_events` stored no address and no browser because the route that records a sign-in did
-- not pass them, and nothing recorded which sign-in-service session a sign-in began, so two devices on one login were
-- indistinguishable and a Partner could not be told.
--
-- 1. `login_events.session_id`: the sign-in service's session id (the `session_id` claim of the access token), recorded with each
--    sign-in and sign-out. Nullable: every row written before this has none, and a token that carries no claim records none.
-- 2. `login_sessions`: one row per (person, session id) with the address and browser first seen, when the server last heard from the
--    session and when it ended. Written by the API only; the signed-in database roles hold nothing on it.
-- 3. `users.other_sessions_revoked_at` and `users.other_sessions_kept_session_id`: "sign out my other sessions". The existing
--    `sessions_revoked_at` ends every session of the person including the one asking, so this is a second, narrower mark: tokens of
--    sessions that began before the instant and are not the kept one are refused; the kept session and any later sign-in are not.
-- 4. `notifications.type` gains `second_device`: the in-app notice to the Partners when a login that already has a live session signs
--    in somewhere else. Derived from migration 450's list (the latest), never from an older one.
--
-- Additive and idempotent. Retention of the address and browser follows `login_events` (domain/dpdp/retention.py, category
-- access_logs); the period is a legal point and sits on the owner's list, not here.

BEGIN;

SELECT set_config('lock_timeout', '15s', true);

-- ── 1. the sign-in record names its session ────────────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.login_events ADD COLUMN IF NOT EXISTS session_id TEXT;
COMMENT ON COLUMN public.login_events.session_id IS
  'POST-A-486, migration 765. The sign-in service''s session id (the access token''s session_id claim) of the sign-in or sign-out, or NULL '
  'where the token carried none or the row predates the column.';

-- ── 2. the sessions a login is signed in on ───────────────────────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.login_sessions (
  id           UUID        PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id      UUID        NOT NULL REFERENCES public.firms(id) ON DELETE CASCADE,
  user_id      UUID        NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
  -- The sign-in service's own id for the session. Not secret on its own (it is a claim in the person's token) and never sent to a screen.
  session_id   TEXT        NOT NULL,
  -- The caller's address as our own proxy wrote it (core/client_ip.py), never the first entry of a forwarded chain the caller typed.
  -- The address and browser the session was FIRST seen with: a later report only moves last_seen_at.
  ip           TEXT,
  user_agent   TEXT,
  started_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- When the server last heard from the session: at sign-in, then every few minutes while somebody is using it.
  last_seen_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  ended_at     TIMESTAMPTZ,
  ended_how    TEXT,
  CONSTRAINT login_sessions_one_per_session UNIQUE (user_id, session_id),
  CONSTRAINT login_sessions_ended_how_is_known
    CHECK (ended_how IS NULL OR ended_how IN ('signed_out', 'other_sessions', 'forced', 'suspended')),
  CONSTRAINT login_sessions_an_end_says_how
    CHECK ((ended_at IS NULL) = (ended_how IS NULL)),
  CONSTRAINT login_sessions_a_session_id_is_not_blank CHECK (btrim(session_id) <> '')
);

COMMENT ON TABLE public.login_sessions IS
  'POST-A-486, migration 765. The sessions of a login: the address and browser first seen, when it was last heard from, and when and how it ended. '
  'Written by the API only. A session counts as live per domain/identity/devices.py; a row is never deleted by the API.';

CREATE INDEX IF NOT EXISTS idx_login_sessions_open_by_member
  ON public.login_sessions (firm_id, user_id, last_seen_at DESC) WHERE ended_at IS NULL;

ALTER TABLE public.login_sessions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "login_sessions_firm_isolation" ON public.login_sessions;
CREATE POLICY "login_sessions_firm_isolation" ON public.login_sessions
  FOR ALL TO authenticated
  USING (firm_id = (SELECT public.get_my_firm_id()))
  WITH CHECK (firm_id = (SELECT public.get_my_firm_id()));

REVOKE ALL ON public.login_sessions FROM PUBLIC, anon, authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.login_sessions TO service_role;

DO $$
BEGIN
    PERFORM public.guard_member_firm('public.login_sessions');
END $$;

-- ── 3. "sign out my other sessions" ───────────────────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.users
  ADD COLUMN IF NOT EXISTS other_sessions_revoked_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS other_sessions_kept_session_id TEXT;

COMMENT ON COLUMN public.users.other_sessions_revoked_at IS
  'POST-A-486, migration 765. When the person last signed out their OTHER sessions: a token of a session that began before this instant '
  'and is not other_sessions_kept_session_id is refused by get_current_user. sessions_revoked_at (suspend, force sign-out) still ends every session.';
COMMENT ON COLUMN public.users.other_sessions_kept_session_id IS
  'POST-A-486, migration 765. The session that asked to sign the others out and so stays.';

-- ── 4. the notice to the Partners ─────────────────────────────────────────────────────────────────────────────────────────────
ALTER TABLE public.notifications DROP CONSTRAINT IF EXISTS notifications_type_check;
ALTER TABLE public.notifications
    ADD CONSTRAINT notifications_type_check CHECK (type IN (
        'task_assigned', 'risk_detected', 'document_processed',
        'compliance_due', 'ai_recommendation', 'status_changed',
        'task_reassigned', 'due_soon', 'overdue', 'task_overdue',
        'recurring_generated',
        'workflow',
        'portal_message',
        -- migration 765: a login that already had a live session signed in on another device
        'second_device'
    ));

COMMENT ON CONSTRAINT notifications_type_check ON public.notifications IS
    'Superset of migration 450''s list (which was a superset of 157''s, then 122''s). The next widening must extend THIS list, found by '
    'number, not re-derive it. Migration 765 added second_device.';

-- ── the closing check ─────────────────────────────────────────────────────────────────────────────────────────────────────────
DO $$
DECLARE
    r text;
    verb text;
BEGIN
    FOREACH r IN ARRAY ARRAY['authenticated', 'anon'] LOOP
        FOREACH verb IN ARRAY ARRAY['SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'] LOOP
            IF has_table_privilege(r, 'public.login_sessions', verb) THEN
                RAISE EXCEPTION 'migration 765: % still holds % on public.login_sessions', r, verb;
            END IF;
        END LOOP;
    END LOOP;
    IF NOT has_table_privilege('service_role', 'public.login_sessions', 'INSERT') THEN
        RAISE EXCEPTION 'migration 765: the API (service_role) cannot write public.login_sessions';
    END IF;
END $$;

COMMIT;
