-- Rollback of migration 767: restores migration 468's public.staff_session_is_live (the token's `iat` alone).

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
