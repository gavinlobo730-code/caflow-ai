-- Rollback of migration 506: puts back migration 153's two own-row policies, which ask only the sign-in id. THIS RE-OPENS THE
-- HOLE: a suspended member, or a session signed out on purpose, reads and renames their own `users` row again.
DROP POLICY IF EXISTS "users_own_row_select" ON public.users;
CREATE POLICY "users_own_row_select" ON public.users
  FOR SELECT TO authenticated
  USING (auth_user_id = (SELECT auth.uid()));

DROP POLICY IF EXISTS "users_own_row_rename" ON public.users;
CREATE POLICY "users_own_row_rename" ON public.users
  FOR UPDATE TO authenticated
  USING (auth_user_id = (SELECT auth.uid()))
  WITH CHECK (auth_user_id = (SELECT auth.uid()));
