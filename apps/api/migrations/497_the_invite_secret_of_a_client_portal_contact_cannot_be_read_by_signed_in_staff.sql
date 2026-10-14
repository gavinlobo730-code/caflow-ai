-- Migration 497 — the invite secret of a client's portal contact cannot be read by signed-in staff
-- (ledger POST-B-027, the half migration 484 left: 484 scoped the ROWS, this hides the SECRET).
--
-- THE HOLE
--   `client_portal_users.invite_token` is a live, single-use invite secret: `accept_portal_invite` finds the pending
--   invite by it (equality) and the code itself calls it "what makes this unforgeable". Accepting also requires the
--   signed-in account's e-mail to equal the contact's e-mail, but that is stated there as defence in depth, so the token is
--   the credential and the e-mail match is a second lock. Migration 163 took INSERT, UPDATE and DELETE away from signed-in
--   users and migration 484 confined a staff member's SELECT to the clients they can reach, but the table-level SELECT
--   grant stayed, so every staff member who can reach a client could still read the token of a contact who has not yet
--   accepted, with their own sign-in. What that lets them do is bounded by the e-mail lock: they would also need an
--   account carrying the contact's address, which depends on whether the sign-up flow confirms an address before it is
--   trusted. That setting lives in the Supabase dashboard and cannot be read from this repository, so this migration does
--   not rely on it. Nothing in the product reads the token that way: the only browser reader of the table lists its
--   columns and leaves the token out, the API reads the table with the service role, and the token is handed to the
--   person who invited the contact once, in the invite call's own response.
--
-- WHAT THIS DOES
--   Replaces the table-level SELECT of `authenticated` with a column-level SELECT on every column EXCEPT `invite_token`,
--   discovered when the migration runs (so a database that has more or fewer columns than production still ends up with
--   exactly the right set). The row policies of 109, 163 and 484 are untouched and still decide WHICH rows.
--
-- WHAT FOLLOWS FROM IT, AND SAYS SO
--   * A `select=*` (or any request that names `invite_token`) as a signed-in user is now a permission error. That is the
--     intended failure: it turns the next reader that forgets the secret is there into an error on the day it is written
--     instead of a token on somebody's screen. The one browser reader names its columns and the API uses the service role.
--   * A column added to this table LATER is not readable by signed-in users until a migration grants it. That is the safe
--     default for a table that holds a credential, and a test names the set that is unreadable so the next person sees it.
--   * The service role, the owner and a connection with no JWT are unaffected. No row, policy or function changes.
--   * Tokens already issued are not rotated: nobody is known to have read one, and a pending invite is the CA's to resend.
--
-- Idempotent: the revoke and the grant are re-run safely, and the closing check fails the migration (and so the deploy) if
-- `authenticated` can still read the secret or cannot read any other column. Reversible: 497_..._rollback.sql restores the
-- table-level SELECT, which RE-OPENS the hole.

DO $$
DECLARE
  cols text;
BEGIN
  SELECT string_agg(quote_ident(column_name), ', ' ORDER BY ordinal_position)
    INTO cols
    FROM information_schema.columns
   WHERE table_schema = 'public'
     AND table_name = 'client_portal_users'
     AND column_name <> 'invite_token';
  IF cols IS NULL THEN
    RAISE EXCEPTION 'migration 497: client_portal_users has no columns other than invite_token, or does not exist';
  END IF;

  EXECUTE 'REVOKE SELECT ON public.client_portal_users FROM authenticated';
  EXECUTE format('GRANT SELECT (%s) ON public.client_portal_users TO authenticated', cols);
END $$;

-- ── the closing check: the secret is unreadable and everything else still is ──────────────────────
DO $$
DECLARE
  c record;
BEGIN
  IF has_table_privilege('authenticated', 'public.client_portal_users', 'SELECT') THEN
    RAISE EXCEPTION 'migration 497: authenticated still holds a table-level SELECT on client_portal_users';
  END IF;
  IF has_column_privilege('authenticated', 'public.client_portal_users', 'invite_token', 'SELECT') THEN
    RAISE EXCEPTION 'migration 497: authenticated can still read invite_token';
  END IF;
  FOR c IN
    SELECT column_name FROM information_schema.columns
     WHERE table_schema = 'public' AND table_name = 'client_portal_users' AND column_name <> 'invite_token'
  LOOP
    IF NOT has_column_privilege('authenticated', 'public.client_portal_users', c.column_name, 'SELECT') THEN
      RAISE EXCEPTION 'migration 497: authenticated cannot read client_portal_users.%', c.column_name;
    END IF;
  END LOOP;
END $$;
