-- Rollback of migration 532: puts `client_year_locks` back as migration 289 left it (the policy that asks a `firm_id` claim no
-- token carries, so it refuses every row to every signed-in session, and the four write grants of the signed-in role), after
-- dropping the six policies 532 created. This restores the DEAD state on purpose: it is what was there, and a rollback that
-- invents a third state is not a rollback. anon's and PUBLIC's access to the table is not given back (neither could read a row).
SELECT set_config('lock_timeout', '15s', true);

DROP POLICY IF EXISTS "client_year_locks_role_delete" ON public.client_year_locks;
DROP POLICY IF EXISTS "client_year_locks_role_update" ON public.client_year_locks;
DROP POLICY IF EXISTS "client_year_locks_role_insert" ON public.client_year_locks;
DROP POLICY IF EXISTS "client_year_locks_internal_partner_only" ON public.client_year_locks;
DROP POLICY IF EXISTS "client_year_locks_assignment_scope" ON public.client_year_locks;
DROP POLICY IF EXISTS "client_year_locks_firm_isolation" ON public.client_year_locks;

-- The predicate is written the way migration 526 left it in the catalog (the claim read once per query, `(SELECT auth.jwt())`),
-- so that this is the exact inverse of the migration and a catalog diff of the database before 532 and after 532 and this file
-- is empty.
CREATE POLICY client_year_locks_firm_isolation ON public.client_year_locks
  FOR ALL
  USING (firm_id = (((SELECT auth.jwt()) ->> 'firm_id'))::uuid)
  WITH CHECK (firm_id = (((SELECT auth.jwt()) ->> 'firm_id'))::uuid);

GRANT SELECT, INSERT, UPDATE, DELETE ON public.client_year_locks TO authenticated;
