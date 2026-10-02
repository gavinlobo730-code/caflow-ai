-- Migration 478 — only a Partner may change who is assigned to a client
-- (security_privacy-34, found by the role-by-table access matrix).
--
-- THE HOLE
--   Migration 022 gave `public.user_client_assignments` two policies:
--
--       firm_members_see_assignments   FOR SELECT  TO authenticated
--                                      USING (firm_id = get_my_firm_id())
--       partners_manage_assignments    FOR ALL     TO authenticated
--                                      USING and WITH CHECK (firm_id = get_my_firm_id())
--
--   The second is named for Partners and has never tested for one. The table
--   is the ONE thing every assignment-scoped policy in the database rests on:
--   `can_access_client()` (084) lets a non-Partner see a client's rows exactly
--   when a row here says so. `authenticated` holds INSERT, UPDATE and DELETE
--   on it (041, 095), and the browser speaks PostgREST with the member's own
--   JWT, so any member of the firm — a Reviewer, an Executive assigned to
--   nothing — could insert a row naming themselves and any client of the
--   firm, and from that statement on read and write that client's books,
--   payroll, bank lines and files. Reproduced against an unmodified migrated
--   schema (constraints intact): an Executive assigned to nothing inserted
--   (firm, self, client B) and then read B's client row and B's vendors. The
--   production guards snapshot of 13-09-2026 holds the same policy with the
--   same command and roles, and a read-only look at production when this
--   migration was commissioned showed the same policy and the same grants.
--
--   The API is not the leak. `routers/assignments.py` guards every write with
--   `rbac("assignment", "write")` (Partner only) and the approval executor
--   (`services/approval_service.py`) runs only behind `approval:approve`
--   (Partner only); the browser never writes the table. The Partner-only rule
--   was a property of two URLs while the table was open to every signed-in
--   member — migration 470's finding about `fx_rates`, one table over.
--
-- WHAT THIS DOES
--   Replaces the one FOR ALL policy with one policy per write command, each
--   TO authenticated and each asking
--
--       firm_id = public.get_my_firm_id()
--       AND public.my_permission('assignment', 'write', 'Partner')
--
--   * THE FIRM TEST stays, so a Partner still reaches only their own firm's
--     rows and cannot write an assignment into another firm.
--   * WHO is asked by the function the route's `rbac()` resolves through, not
--     by a role name: `my_permission` honours a per-person grant or denial in
--     the access grid (migration 403/415) exactly as `rbac("assignment",
--     "write")` does, so a firm that deliberately gave one person this
--     permission gets the same answer in both places, and a Partner denied it
--     is denied in both. `get_my_user_id()` and `get_my_role()` already answer
--     NULL for a suspended or signed-out member (468), so they have none.
--   * INSERT carries WITH CHECK, UPDATE both USING and WITH CHECK (a row cannot
--     be re-pointed at another firm), DELETE USING: the three commands the
--     old policy covered, with the same conditions on each.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--   * `firm_members_see_assignments` (SELECT) is untouched. `core/authz.
--     assigned_client_ids` and `is_client_assigned` read the CALLER'S OWN rows
--     under the caller's JWT when USE_USER_JWT is on, so an Executive must keep
--     reading this table; narrowing it to the caller's own rows plus a
--     Manager's firm-wide read is a decision of its own and is not made here.
--   * No other policy, grant or table changes. The eleven other classes of gap
--     the access matrix reports (a Reviewer's writes, payroll's tier, the
--     tables with no client column, ...) are role-tier decisions for the owner
--     and stay reported in tests/test_rls_role_by_table_matrix_pg.py.
--   * No backfill and no row is removed: every assignment already recorded
--     stays, including any a member may have written for themselves while the
--     policy was open. Reading the table for rows nobody with the permission
--     made is a question about data, not a schema change, and is not answered
--     here.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, and the closing check
-- fails the migration (and so the deploy) if the old policy is still there or
-- any of the three is missing. Reversible:
-- 478_only_a_partner_may_change_who_is_assigned_to_a_client_rollback.sql
-- restores 022's FOR ALL policy exactly, which RE-OPENS the hole.

DROP POLICY IF EXISTS "partners_manage_assignments" ON public.user_client_assignments;

DROP POLICY IF EXISTS "partners_insert_assignments" ON public.user_client_assignments;
CREATE POLICY "partners_insert_assignments" ON public.user_client_assignments
  FOR INSERT TO authenticated
  WITH CHECK (
    firm_id = public.get_my_firm_id()
    AND public.my_permission('assignment', 'write', 'Partner')
  );

DROP POLICY IF EXISTS "partners_update_assignments" ON public.user_client_assignments;
CREATE POLICY "partners_update_assignments" ON public.user_client_assignments
  FOR UPDATE TO authenticated
  USING (
    firm_id = public.get_my_firm_id()
    AND public.my_permission('assignment', 'write', 'Partner')
  )
  WITH CHECK (
    firm_id = public.get_my_firm_id()
    AND public.my_permission('assignment', 'write', 'Partner')
  );

DROP POLICY IF EXISTS "partners_delete_assignments" ON public.user_client_assignments;
CREATE POLICY "partners_delete_assignments" ON public.user_client_assignments
  FOR DELETE TO authenticated
  USING (
    firm_id = public.get_my_firm_id()
    AND public.my_permission('assignment', 'write', 'Partner')
  );

DO $$
DECLARE
  n_new int;
  n_old int;
BEGIN
  SELECT count(*) INTO n_new
    FROM pg_policies
   WHERE schemaname = 'public' AND tablename = 'user_client_assignments'
     AND policyname IN ('partners_insert_assignments', 'partners_update_assignments',
                        'partners_delete_assignments')
     AND permissive = 'PERMISSIVE';
  SELECT count(*) INTO n_old
    FROM pg_policies
   WHERE schemaname = 'public' AND tablename = 'user_client_assignments'
     AND policyname = 'partners_manage_assignments';
  IF n_new <> 3 OR n_old <> 0 THEN
    RAISE EXCEPTION 'migration 478: expected three write policies and no partners_manage_assignments, found % and %',
      n_new, n_old;
  END IF;
END $$;
