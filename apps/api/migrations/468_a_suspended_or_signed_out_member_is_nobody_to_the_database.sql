-- Migration 468 — a suspended member, or a session signed out on purpose, is
-- NOBODY to the database (security_privacy-01).
--
-- THE HOLE
--   `suspend_user` and `force_logout` set `users.is_active` and
--   `users.sessions_revoked_at`, and exactly one reader looks at either of them:
--   core/auth.py, on the FastAPI path. The browser reads about 83 tables
--   directly over PostgREST and uploads and lists files through Storage, and
--   every one of those requests is authorised by RLS — whose helpers
--
--       get_my_firm_id()   019
--       get_my_role()      073 (search_path pinned by 144)
--       get_my_user_id()   079 (search_path pinned by 144)
--
--   select the caller's `users` row by `auth_user_id` and test NOTHING else. So
--   a member dismissed on Monday kept reading every client's books on Tuesday
--   through the same JWT, and went on being issued a new one by the refresh
--   token, because nothing told Supabase Auth either. The Partner pressed
--   "Suspend", the screen said "Suspended", and the only door it closed was
--   the one the browser does not use.
--
-- WHAT THIS DOES — ONE RULE, ONE PLACE
--   `staff_session_is_live(is_active, sessions_revoked_at)` is the SQL twin of
--   the two tests core/auth.py makes, and the three helpers each ask it. A
--   session is live when
--
--     (1) the row is not explicitly `is_active = false` — NULL reads as active,
--         which is core/auth.py's `is_active is False` and keeps every row that
--         predates the column working; and
--     (2) either nothing was ever revoked, or the JWT's `iat` is NOT BEFORE the
--         revocation instant (`>=`: core/auth.py refuses only `iat <
--         revoked_epoch`).
--
--   When a revocation exists and the token cannot show when it was issued — no
--   `iat`, or one that is not a number — the answer is FALSE. core/auth.py
--   FAILS CLOSED there on purpose (SECURITY-PRIVACY-21), and a policy that read
--   an unreadable token as live would reopen at the database the exact door that
--   was closed at the API. A revocation is a decision somebody made; a claim the
--   database cannot read is not evidence it was withdrawn.
--
--   A helper that is not live returns NULL, the same thing it returns for a
--   caller with no `users` row at all (a portal client, an employee, the
--   backend's own service key). So no policy needed teaching anything: every
--   `firm_id = get_my_firm_id()` is already false for NULL, every `role IN (...)`
--   already false, and the answer for a suspended member is now what it always
--   was for a stranger.
--
-- WHY THE HELPERS AND NOT EACH POLICY
--   83 tables and 61 call sites of `get_my_role()` across 32 migrations. A
--   per-policy test is 83 chances to miss one and a new table is another; the
--   helpers are the seam, which is also why migration 403 resolved per-person
--   access in `rbac()` rather than beside each guard.
--
-- TWO FUNCTIONS READ `users` INLINE AND WOULD HAVE BEEN LEFT OPEN
--   `can_access_client` (084) joined `users` for its ASSIGNMENT leg and
--   `my_permission` (415) joined it to find the member's grid row. Each would
--   have answered for a suspended member whose role leg had just been closed:
--   an assignment row still exists after a suspension, and so does a grid row
--   that says `granted = true`. Both now ask `get_my_user_id()` instead of
--   reading `users`, so there is exactly ONE place a request becomes a person.
--   `tests/test_a_suspended_member_is_nobody_to_the_database_pg.py` holds that
--   as a rule over the whole catalogue rather than a list of these two.
--
-- DERIVED FROM THE LAST DEFINER OF EACH, FOUND BY NUMBER
--   get_my_firm_id   019 (SECURITY DEFINER, STABLE, search_path public, pg_catalog)
--   get_my_role      073's body + 144's search_path
--   get_my_user_id   079's body + 144's search_path
--   can_access_client 084 (search_path = public — NOT pg_catalog, kept as it was)
--   my_permission    415 (plpgsql — the three states need ONE lookup)
--   `CREATE OR REPLACE` keeps owner, grants and comments, so none are restated.
--   `COALESCE(... = 'Partner', FALSE)` is the one addition: a caller who is not
--   live has a NULL role, and `FALSE OR NULL OR FALSE` is NULL, which `IF NOT
--   can_access_client(...)` in the ten RPCs that ask it reads as "no refusal".
--   Every one of them refuses a NULL firm first, so none was open — but a
--   function whose answer is three-valued is one reordered guard from being, and
--   the answer to "may this person see this client" has two values.
--   The firm-level `p_client_id IS NULL` leg of can_access_client is unchanged
--   and deliberately so: it answers "this row belongs to no client", the firm
--   leg of every policy decides whether the CALLER may see firm rows, and a
--   suspended member's firm leg is now NULL.
--
-- WHAT IS NOT DONE HERE, AND WHY
--   * Supabase Auth's own ban / sign-out on suspend. A banned auth user cannot
--     refresh, but the database no longer honours the refresh either, and the
--     ban is a second system to keep in step with `is_active` (an unban on
--     reactivate that fails leaves a reactivated member unable to sign in).
--   * `force_logout` still lets the member sign in again: it revokes sessions,
--     it does not forbid a new one — that is its meaning, now at the database
--     as well.
--   * A suspended or soft-deleted FIRM. core/auth.py refuses every user of one;
--     the helpers do not ask `firms` and a member of a suspended firm still
--     reads over PostgREST. Named, not changed: it is a different switch with
--     a different owner (the platform administrator).
--
-- Idempotent (CREATE OR REPLACE). Reversible:
-- 468_a_suspended_or_signed_out_member_is_nobody_to_the_database_rollback.sql.

-- ── the one rule ─────────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.staff_session_is_live(
  p_is_active           boolean,
  p_sessions_revoked_at timestamptz
)
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = public, pg_catalog
AS $$
  SELECT COALESCE(p_is_active, TRUE)
     AND CASE
           -- Nothing was ever revoked: the claim is never read, so the common
           -- case costs no JSON parse.
           WHEN p_sessions_revoked_at IS NULL THEN TRUE
           -- `iat` is a number of seconds. A value that is not one cannot be
           -- compared and is read as NOT live (core/auth.py fails closed).
           WHEN (auth.jwt() ->> 'iat') ~ '^[0-9]+(\.[0-9]+)?$'
             THEN (auth.jwt() ->> 'iat')::numeric
                    >= extract(epoch FROM p_sessions_revoked_at)
           ELSE FALSE
         END
$$;

COMMENT ON FUNCTION public.staff_session_is_live(boolean, timestamptz) IS
  'Is this staff session still allowed? The SQL twin of core/auth.py: not '
  'explicitly is_active=false, and the JWT iat not before sessions_revoked_at '
  '(a revocation with no readable iat is NOT live). Asked by get_my_firm_id, '
  'get_my_role and get_my_user_id — the only place the question is answered. '
  'Migration 468.';

-- Nobody calls this from a request: it is read by three SECURITY DEFINER
-- helpers, which run as the owner. Taking it away from every role a request
-- can arrive as keeps it from becoming a second thing a client can probe.
REVOKE ALL ON FUNCTION public.staff_session_is_live(boolean, timestamptz)
  FROM PUBLIC, anon, authenticated;

-- ── the three helpers ────────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION public.get_my_firm_id()
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT u.firm_id
    FROM public.users u
   WHERE u.auth_user_id = auth.uid()
     AND public.staff_session_is_live(u.is_active, u.sessions_revoked_at)
   LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.get_my_role()
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT u.role
    FROM public.users u
   WHERE u.auth_user_id = auth.uid()
     AND public.staff_session_is_live(u.is_active, u.sessions_revoked_at)
   LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.get_my_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT u.id
    FROM public.users u
   WHERE u.auth_user_id = auth.uid()
     AND public.staff_session_is_live(u.is_active, u.sessions_revoked_at)
   LIMIT 1;
$$;

-- ── the two that read `users` themselves ─────────────────────────────────────
CREATE OR REPLACE FUNCTION public.can_access_client(p_client_id text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    p_client_id IS NULL
    OR COALESCE(public.get_my_role() = 'Partner', FALSE)
    OR EXISTS (
      SELECT 1
        FROM public.user_client_assignments a
       WHERE a.user_id = public.get_my_user_id()
         AND a.client_id::text = p_client_id
    );
$$;

CREATE OR REPLACE FUNCTION public.my_permission(
  resource      text,
  action        text,
  minimum_role  text
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_granted boolean;
BEGIN
  -- The person's own answer, if they have one. `granted` is NOT NULL and the
  -- ROW is what is optional, so "no opinion" has exactly one spelling and a
  -- NULL here means only that no row was found — which is also what a member
  -- who is no longer live gets, because get_my_user_id() is NULL for them.
  SELECT up.granted
    INTO v_granted
    FROM public.user_permissions up
   WHERE up.user_id = public.get_my_user_id()
     AND up.resource = my_permission.resource
     AND up.action   = my_permission.action
   LIMIT 1;

  IF v_granted IS NULL THEN
    -- No row: the role decides, at the minimum this policy names.
    RETURN public.my_role_at_least(minimum_role);
  END IF;

  IF v_granted IS FALSE
     AND public.role_rank(public.get_my_role()) >= public.role_rank('Partner')
     AND (my_permission.resource, my_permission.action) IN
         (('team','read'), ('team','write'), ('firm','read'), ('firm','admin'))
  THEN
    -- A Partner keeps the four pairs that reach the access screen itself,
    -- whatever the grid says. See migration 415's header.
    RETURN true;
  END IF;

  RETURN v_granted;
END;
$$;
