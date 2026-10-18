-- Migration 506: a suspended member, or a session signed out on purpose, does not read or rename their own `users` row.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG (ledger POST-A-013, found by the role-by-table matrix of migration 468's follow-up)
-- ═══════════════════════════════════════════════════════════════════════════
-- Migration 468 made a suspended member (`users.is_active = false`) and a session signed out on purpose (the JWT's `iat`
-- before `users.sessions_revoked_at`) NOBODY to the database: the three helpers `get_my_firm_id()`, `get_my_role()` and
-- `get_my_user_id()` ask `staff_session_is_live(...)` and answer NULL otherwise, so every policy that compares to one of them
-- is false for that member. Two policies do not compare to a helper. Migration 153 wrote them directly against the sign-in id:
--
--     users_own_row_select  FOR SELECT  USING (auth_user_id = (SELECT auth.uid()))
--     users_own_row_rename  FOR UPDATE  USING / WITH CHECK (auth_user_id = (SELECT auth.uid()))
--
-- so a suspended member still read their own `users` row (role, firm, e-mail, the revocation timestamp) and could still
-- rename themselves, the one write the column grant of 246 leaves a signed-in role (`UPDATE (full_name)`). The exposure is
-- small (only the member's own row), and the role-by-table matrix recorded it as the last frozen deviation
-- (`suspended-member-keeps-their-own-user-row`, two cells), but it contradicts the rule that a suspended member reaches
-- nothing but reference data, and every other cell of that matrix obeys it.
--
-- BEFORE CHANGING IT, WHAT NEEDS A SUSPENDED MEMBER'S OWN ROW WAS CHECKED. Nothing does:
--   * the API's sign-in path (`core/auth.py`) reads the row with the service role, not the member's own session, and
--     refuses a suspended member itself with its own sentence (403);
--   * no screen in `apps/web` reads `is_active` or `sessions_revoked_at` of the signed-in member over PostgREST (the team
--     screen reads other members' rows, which a Partner's policy reaches, and a Partner who is live);
--   * a suspended member whose browser then asks for their firm or role gets none, which is the same answer a stranger gets.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═══════════════════════════════════════════════════════════════════════════
-- Re-creates the two policies with one more condition: `id = (SELECT public.get_my_user_id())`. `get_my_user_id()` is
-- SECURITY DEFINER and returns the caller's `users.id` only while `staff_session_is_live(...)` holds (migration 468), so the
-- liveness rule stays in ONE place. `staff_session_is_live` itself cannot be called from a policy: migration 468 revoked it
-- from every role a request can arrive as, which is why a policy asks the helper. The sign-in-id test is kept beside it, so a
-- member still reaches exactly their own row and nobody else's.
--
-- Nothing else changes. The column grant (`UPDATE (full_name)`) is untouched, and so is every other policy on `users`.
-- Derived from the only migration that defines these two policies (153, found by number: 246 and 287 mention them and
-- do not redefine them).

DROP POLICY IF EXISTS "users_own_row_select" ON public.users;
CREATE POLICY "users_own_row_select" ON public.users
  FOR SELECT TO authenticated
  USING (auth_user_id = (SELECT auth.uid()) AND id = (SELECT public.get_my_user_id()));

DROP POLICY IF EXISTS "users_own_row_rename" ON public.users;
CREATE POLICY "users_own_row_rename" ON public.users
  FOR UPDATE TO authenticated
  USING (auth_user_id = (SELECT auth.uid()) AND id = (SELECT public.get_my_user_id()))
  WITH CHECK (auth_user_id = (SELECT auth.uid()) AND id = (SELECT public.get_my_user_id()));
