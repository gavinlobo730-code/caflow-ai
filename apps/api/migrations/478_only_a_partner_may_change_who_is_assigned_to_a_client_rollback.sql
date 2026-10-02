-- Rollback for migration 478: the three write policies go away and migration
-- 022's single FOR ALL policy comes back exactly as 022 wrote it.
--
-- Rolling back RE-OPENS the hole 478 closes: any member of a firm can write a
-- row into user_client_assignments naming themselves and any client of the
-- firm, which `can_access_client()` then honours.

DROP POLICY IF EXISTS "partners_insert_assignments" ON public.user_client_assignments;
DROP POLICY IF EXISTS "partners_update_assignments" ON public.user_client_assignments;
DROP POLICY IF EXISTS "partners_delete_assignments" ON public.user_client_assignments;

DROP POLICY IF EXISTS "partners_manage_assignments" ON public.user_client_assignments;
CREATE POLICY "partners_manage_assignments" ON public.user_client_assignments
  FOR ALL TO authenticated
  USING (firm_id = public.get_my_firm_id())
  WITH CHECK (firm_id = public.get_my_firm_id());
