-- Migration 773: the database knows "sign out my other sessions" (ledger POST-A-509).
--
-- WHAT WAS WRONG
-- "Sign out my other sessions" (POST-A-486) writes two marks on the person's own users row: other_sessions_revoked_at (the
-- instant) and other_sessions_kept_session_id (the session that asked to stay). The API refuses a token whose session is not
-- the kept one and began before the instant (core/auth_time.ended_by_other_sessions_sign_out, asked by get_current_user). The
-- database did not know either mark: public.staff_session_is_live, the one question get_my_firm_id, get_my_role and
-- get_my_user_id ask on every request that reaches a table directly over PostgREST, read users.is_active and
-- users.sessions_revoked_at and nothing else (migrations 468 and 767). So a session the person had signed out that way was
-- refused by the API and still read, through the database's own door, every row a signed-in session can reach there (the
-- browser stopped reading payroll, bank and document tables with POST-A-010, so the exposure is narrow, and it was not tried
-- live). The Security screen's sentence "PracticeSync's own server refuses them from now on" was true and said no more.
--
-- WHAT THIS DOES
-- * public.token_session_began_at_or_after(instant) is the token side of the question, written once: the token's `iat` is not
--   before the instant AND the OLDEST stamp in its `amr` is not before it (the rule migration 767 wrote inline, moved here with
--   one addition: no instant at all is a session that began after it, which 767 said by testing for NULL first). A renewed token
--   has a new `iat` and carries the stamps of the session it renews, and the oldest stamp is when the session began. A token whose
--   `iat` is missing or not a number did NOT begin after the instant (the API fails closed there).
-- * public.staff_session_is_live takes the two marks as well, and a session is live when it is not explicitly inactive and
--     - nothing ever ended every session, or the token began at or after that instant (sessions_revoked_at: suspend, force
--       sign-out; unchanged from 767), and
--     - nobody ever signed out the other sessions, or this token IS the session that asked to stay (its `session_id` claim is a
--       non-blank string equal to the kept id), or it began at or after that instant. The kept session is judged by its id
--       first, as the API does, so it is live whatever its `iat` shows; a token with no session id cannot be the kept one.
--   Both conditions apply together, as they do in get_current_user: the kept session is still ended by a revocation of all.
--   The answer is always TRUE or FALSE, never NULL (the whole expression is wrapped in COALESCE(..., FALSE)): a token with no
--   `session_id` claim made the kept-session test NULL, which the three helpers read as "no row" (so nobody got in), but a function
--   that answers a yes-or-no question with a third value is one `IF NOT f()` away from reading it as "no refusal" (migration 468's
--   header says the same about can_access_client). "Non-blank" is SQL's btrim, which trims spaces; the API's `str.strip()` trims every
--   Unicode whitespace. The two differ only for a kept id made of tabs or no-break spaces, which the writer (it stores the API's own
--   `session_id_of`, never blank) cannot produce and only a hand-written row could, and for which the token's claim, signed by the
--   sign-in service, would have to be that same whitespace.
-- * The three helpers pass the two marks, which they already have: each selects the caller's users row. Each is derived from
--   migration 468, the last migration that defines it (found by number).
--   Their owner, grants and comments are untouched (CREATE OR REPLACE), and so is every policy: they ask these three. Nothing after
--   468 defines, alters or grants them.
-- * The old two-argument function is dropped in the same migration, after the helpers stop calling it, so the question is
--   answered in exactly one place and a caller cannot ask the half of it. Nothing outside the three helpers called it.
--
-- tests/test_773_the_database_knows_a_person_signed_out_their_other_sessions_pg.py holds the database equal to core/auth_time over
-- a table of tokens and marks, as migration 767's test does for the first mark.
-- Functions only: nothing is created, altered or written in a table. Reversible: 773_..._rollback.sql restores 767's function and
-- 468's helper bodies. Applied with the API already deployed: the API does not call these functions, so there is nothing to order
-- going FORWARD. Going BACK there is one order: roll back 773 BEFORE 765. The helpers read users.other_sessions_revoked_at and
-- users.other_sessions_kept_session_id, a function body records no dependency on a column, and 765's rollback drops both columns
-- without complaint, after which every helper call fails with 42703 and every request checked by row security fails with it. The API
-- survives the same state (core/auth._read_user_row falls back on 42703); the database would not. 765's rollback says so too.

CREATE OR REPLACE FUNCTION public.token_session_began_at_or_after(p_instant timestamptz)
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = public, pg_catalog
AS $$
  SELECT CASE
           -- No instant to be before: nothing was ever revoked. The caller asks first, so the common case reads no claim at all.
           WHEN p_instant IS NULL THEN TRUE
           -- `iat` is a number of seconds. A value that is not one cannot be compared and is read as NOT live (fail closed).
           WHEN (auth.jwt() ->> 'iat') ~ '^[0-9]+(\.[0-9]+)?$'
             THEN (auth.jwt() ->> 'iat')::numeric >= extract(epoch FROM p_instant)
                  -- The session must also have BEGUN at or after the instant: its oldest `amr` stamp. No stamp is no objection
                  -- (the token is then judged by `iat` alone). A list that is not one, entries that are not objects and a
                  -- `timestamp` that is not a number are read as carrying no stamp, which is what the API's `_stamps` does.
                  AND COALESCE((
                        SELECT min((e ->> 'timestamp')::numeric)
                          FROM jsonb_array_elements(
                                 CASE WHEN jsonb_typeof(auth.jwt() -> 'amr') = 'array'
                                      THEN auth.jwt() -> 'amr' ELSE '[]'::jsonb END) AS e
                         WHERE jsonb_typeof(e) = 'object' AND jsonb_typeof(e -> 'timestamp') = 'number'
                      ), extract(epoch FROM p_instant)) >= extract(epoch FROM p_instant)
           ELSE FALSE
         END
$$;

COMMENT ON FUNCTION public.token_session_began_at_or_after(timestamptz) IS
  'Does the session this token belongs to begin at or after an instant? The SQL twin of the negation of core/auth_time.'
  'issued_before_revocation: the token''s iat is not before it AND the oldest amr stamp is not before it; a token with no '
  'readable iat is not; no instant at all is TRUE. Asked by staff_session_is_live for both marks. Migration 773 (the rule is '
  'migration 767''s, moved here).';

CREATE OR REPLACE FUNCTION public.staff_session_is_live(
  p_is_active                      boolean,
  p_sessions_revoked_at            timestamptz,
  p_other_sessions_revoked_at      timestamptz,
  p_other_sessions_kept_session_id text
)
RETURNS boolean
LANGUAGE sql
STABLE
SET search_path = public, pg_catalog
AS $$
  -- TRUE or FALSE and never NULL: a token with no `session_id` claim makes the kept-session test NULL, and FALSE OR NULL OR FALSE is NULL.
  SELECT COALESCE(
    COALESCE(p_is_active, TRUE)
     -- Every session ended (a suspension, a force sign-out). Nothing revoked: no claim is read, so the common case costs no JSON parse.
     AND (p_sessions_revoked_at IS NULL OR public.token_session_began_at_or_after(p_sessions_revoked_at))
     -- Every session but the one that asked to stay (POST-A-486).
     AND (p_other_sessions_revoked_at IS NULL
          OR (COALESCE(p_other_sessions_kept_session_id, '') <> ''
              AND jsonb_typeof(auth.jwt() -> 'session_id') = 'string'
              AND btrim(auth.jwt() ->> 'session_id') <> ''
              AND auth.jwt() ->> 'session_id' = p_other_sessions_kept_session_id)
          OR public.token_session_began_at_or_after(p_other_sessions_revoked_at)),
    FALSE)
$$;

COMMENT ON FUNCTION public.staff_session_is_live(boolean, timestamptz, timestamptz, text) IS
  'Is this staff session still allowed? The SQL twin of core/auth.py and core/auth_time.py: not explicitly is_active=false; '
  'the token began at or after sessions_revoked_at (suspend, force sign-out: every session); and, where the person signed out '
  'their other sessions, the token is the session that asked to stay or began at or after other_sessions_revoked_at. Where a '
  'mark applies and the token is not the kept session, a token with no readable iat is not live. Always TRUE or FALSE, never '
  'NULL. Asked by get_my_firm_id, get_my_role and get_my_user_id, the only place the question is answered. Migrations 468, '
  '767 and 773.';

-- The three helpers pass the person's two marks beside the two they already passed. Bodies as migration 468 wrote them.
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
     AND public.staff_session_is_live(u.is_active, u.sessions_revoked_at, u.other_sessions_revoked_at, u.other_sessions_kept_session_id)
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
     AND public.staff_session_is_live(u.is_active, u.sessions_revoked_at, u.other_sessions_revoked_at, u.other_sessions_kept_session_id)
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
     AND public.staff_session_is_live(u.is_active, u.sessions_revoked_at, u.other_sessions_revoked_at, u.other_sessions_kept_session_id)
   LIMIT 1;
$$;

-- Nothing calls the two-argument function any more.
DROP FUNCTION IF EXISTS public.staff_session_is_live(boolean, timestamptz);

-- As 468 did: nobody calls these from a request; the three SECURITY DEFINER helpers run as the owner and read them.
REVOKE ALL ON FUNCTION public.staff_session_is_live(boolean, timestamptz, timestamptz, text) FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.token_session_began_at_or_after(timestamptz) FROM PUBLIC, anon, authenticated;
