-- Rollback of migration 773 (POST-A-509): the database stops knowing "sign out my other sessions".
-- Restores migration 767's two-argument staff_session_is_live and migration 468's three helper bodies, in that order (the helpers must
-- have a function to call before the four-argument one is dropped), then drops the two functions 773 created. After it a session the
-- person signed out with "sign out my other sessions" is refused by the API again and no longer by the database's own door.
-- RUN THIS BEFORE 765's rollback, never after: the bodies 773 installs read users.other_sessions_revoked_at and
-- users.other_sessions_kept_session_id, and once 765's rollback has dropped those columns every helper call fails with 42703.

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
           WHEN p_sessions_revoked_at IS NULL THEN TRUE
           WHEN (auth.jwt() ->> 'iat') ~ '^[0-9]+(\.[0-9]+)?$'
             THEN (auth.jwt() ->> 'iat')::numeric >= extract(epoch FROM p_sessions_revoked_at)
                  AND COALESCE((
                        SELECT min((e ->> 'timestamp')::numeric)
                          FROM jsonb_array_elements(
                                 CASE WHEN jsonb_typeof(auth.jwt() -> 'amr') = 'array'
                                      THEN auth.jwt() -> 'amr' ELSE '[]'::jsonb END) AS e
                         WHERE jsonb_typeof(e) = 'object' AND jsonb_typeof(e -> 'timestamp') = 'number'
                      ), extract(epoch FROM p_sessions_revoked_at)) >= extract(epoch FROM p_sessions_revoked_at)
           ELSE FALSE
         END
$$;

COMMENT ON FUNCTION public.staff_session_is_live(boolean, timestamptz) IS
  'Is this staff session still allowed? The SQL twin of core/auth.py and core/auth_time.py: not explicitly '
  'is_active=false, and the token neither issued before sessions_revoked_at nor part of a session whose oldest '
  'amr stamp is before it (a renewed token of a signed-out session is NOT live; a revocation with no readable iat is NOT '
  'live). Asked by get_my_firm_id, get_my_role and get_my_user_id, the only place the question is answered. '
  'Migrations 468 and 767.';

REVOKE ALL ON FUNCTION public.staff_session_is_live(boolean, timestamptz) FROM PUBLIC, anon, authenticated;

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

DROP FUNCTION IF EXISTS public.staff_session_is_live(boolean, timestamptz, timestamptz, text);
DROP FUNCTION IF EXISTS public.token_session_began_at_or_after(timestamptz);
