-- Migration 767: a renewed token of a signed-out session is not live to the database (ledger POST-A-494).
--
-- WHAT WAS WRONG
-- Revoking a person's sessions (a Partner's force sign-out, a platform suspension) stamps users.sessions_revoked_at, and
-- the API refuses a token whose session began before it (core/auth_time.issued_before_revocation, POST-A-482): the
-- token's `iat` is when THIS token was issued, and the browser renews its token hourly and on every 401, so a renewed
-- token of a signed-out session has an `iat` after the revocation. The token's `amr` list carries the stamps of the
-- session it renews (the person's sign-in), and its oldest stamp is when the session began.
-- public.staff_session_is_live (migration 468) compared `iat` alone. So the API refused the signed-out browser and the
-- database did not: the same browser, renewing its token, read again every table a signed-in session can still reach
-- directly over PostgREST (the browser stopped reading payroll, bank and document tables with POST-A-010, so the exposure
-- is narrow, and it was not tried live).
--
-- WHAT THIS DOES
-- Replaces the function with the API's own rule, same name and arguments, derived from migration 468 (the only migration
-- that defines it; 506 and the helpers only call it). A session is live when it is not explicitly inactive and either
-- nothing was ever revoked, or BOTH
--   * the token's `iat` is not before the revocation (the old rule, unchanged, and still failing closed when the token
--     shows no readable `iat`), and
--   * the OLDEST stamp in the token's `amr` is not before it. A token with no `amr`, one that is not a list, and entries
--     that are not objects or whose `timestamp` is not a number are read as carrying no stamp, which is what the API's
--     `_stamps` does, so such a token is judged by `iat` alone as it always was.
-- The OLDEST stamp, not the newest: a person whose sessions were revoked and who still holds the old session can enter an
-- authenticator code against it, which adds a stamp AFTER the revocation; judging by the newest would read the old session
-- as a fresh sign-in. A genuinely new sign-in has every stamp after the revocation.
-- The three helpers (get_my_firm_id, get_my_role, get_my_user_id) and every policy are untouched: they ask this function.
-- The "sign out my other sessions" mark (users.other_sessions_revoked_at, migration 765) is still the API's alone, and is
-- recorded as POST-A-509.
--
-- tests/test_a_suspended_member_is_nobody_to_the_database_pg.py holds this equal to core/auth_time over a table of tokens.
-- Function only; nothing is created, altered or written. Reversible: 767_..._rollback.sql restores 468's body.
-- Applied with the API already deployed: the API does not call this function, so there is nothing to order.


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
           -- Nothing was ever revoked: no claim is read, so the common case costs no JSON parse.
           WHEN p_sessions_revoked_at IS NULL THEN TRUE
           -- `iat` is a number of seconds. A value that is not one cannot be compared and is read as NOT live (fail closed).
           WHEN (auth.jwt() ->> 'iat') ~ '^[0-9]+(\.[0-9]+)?$'
             THEN (auth.jwt() ->> 'iat')::numeric >= extract(epoch FROM p_sessions_revoked_at)
                  -- The session must also have BEGUN at or after the revocation: its oldest `amr` stamp. No stamp is no
                  -- objection (the token is then judged by `iat` alone).
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

-- Unchanged from 468: nobody calls this from a request, it is read by three SECURITY DEFINER helpers.
REVOKE ALL ON FUNCTION public.staff_session_is_live(boolean, timestamptz) FROM PUBLIC, anon, authenticated;
