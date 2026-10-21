-- Migration 530 — a grant of access names a member of the firm, and a client of the firm, that writes it, and a grant that
-- does not grants nothing (POST-A-308, found by the independent review of migration 529 and reproduced; the same hole one
-- table over found by the independent review of this one).
--
-- THE HOLE
--
--   Two tables decide what a member of a firm may reach, and both are written by a Partner:
--
--       public.user_client_assignments (firm_id, user_id, client_id)    which clients a member who is not a Partner may see:
--                                                                        `my_assigned_client_ids()` (526) and
--                                                                        `can_access_client()` (084, 468) read it
--       public.user_permissions (firm_id, user_id, resource, action, granted)   what a member may do, beyond or below their
--                                                                        role: `my_permission()` (415, 468) reads it
--
--   Migration 478 made writing the first a Partner's act, and 403/415 gave the second a Partner-only write policy; both ask
--   that the ROW's `firm_id` is the caller's firm and nothing about the member the row names, or, for an assignment, the
--   client. All three readers look the table up by the member alone, with no firm. So a Partner of firm G can insert
--   (firm_id = G, user_id = a member of firm F, client_id = a client of F), or (G, a member of F, 'assignment', 'write', true),
--   and from that statement on F's member reads rows of F's clients that F never assigned them, or may assign themselves
--   the rest; and F's own Partners cannot see or remove the row, because its firm is G, so the grant lasts. Reproduced on a
--   throwaway database on 21-10-2026 (the assignment by the review of 529 and again by me; the permission by the review of
--   this migration, who gave F's Manager `assignment:write`, had them assign themselves F's other two clients and watched
--   their customers go from one to three). The same row can also take a permission AWAY from F's member
--   (`granted = false`). It needs the member's UUID and, for an assignment, a client's, which nothing serves, or a person who
--   holds an account in both firms (a freelance CA who is a Manager in one practice and the Partner of their own; one login
--   cannot sit in two firms, so that is two logins). Nothing of the API is involved on the way in: `routers/assignments.py` and
--   `services/user_permission_service` check the pair against the caller's firm. The rule was a property of the URL while the
--   table took any firm-matching row, and the two API-side readers of the rows looked them up by the member alone (below).
--
-- WHAT THIS DOES
--
--   1. Two helpers, `user_is_in_my_firm(uuid)` and `client_is_in_my_firm(uuid)`: is this user (client) a member (client) of the
--      caller's firm. They are SECURITY DEFINER because a plain subquery in a policy cannot be used: `public.users` shows a
--      Partner only their OWN row to their own sign-in (`users_own_row_select`, migration 153, restated by 506; the assignment router reads the
--      members through the repository for the same reason), so a policy that asked `users` as the caller would refuse every
--      legitimate grant to somebody else. Each answers about the CALLER'S firm only (`get_my_firm_id()`, NULL for a suspended or
--      signed-out member, so false): a foreign id and an id that does not exist answer the same word. They do confirm, to
--      anyone signed in, that an id they already hold belongs to their own firm (the internal practice's client included);
--      nothing about another firm. EXECUTE goes to `authenticated` and `service_role` only; the policies they sit in are
--      `TO authenticated`.
--   2. `partners_insert_assignments` and `partners_update_assignments` ask both helpers in the WITH CHECK, and
--      `firm_user_permissions` (a FOR ALL policy; its USING is left as it is) asks the first, so a grant cannot be written, or
--      re-pointed, onto a member or a client of another firm. The expressions keep the once-per-query form 525 gave them.
--   3. `my_assigned_client_ids()` and `can_access_client()` count only a row of the caller's own firm whose client belongs to
--      that firm, and `my_permission()` reads only a row of the caller's own firm, so a row that is already in either table,
--      which the policies cannot reach, grants nothing from now on. All three are replaced WHOLE from their last definitions
--      (526, 468 and 468) with the firm added to each (and, for the two assignment readers, the client's firm) and keep their owner, search_path, volatility and grants. The assigned
--      clients are read with the member's firm and user taken ONCE, as scalar sub-selects, and a join to the client: measured
--      as a Manager with 3,000 assignments, calling the firm function once per row cost 160 ms against 2 ms before, and this
--      form costs what the old one did.
--   4. A WARNING with the number of rows in each table that name a member or a client of another firm than their own, so the
--      apply log says whether any exist. It is a WARNING and not a NOTICE because the production runner runs psql at
--      client_min_messages=warning and throws away a clean run's output: a NOTICE here reached nobody, which the review of
--      this migration showed by planting two rows and applying it through the runner. The runner keeps a line that opens
--      with `migration <number>:` and shows it in its report and as an annotation on the run. NONE ARE REMOVED: deleting an access row is a decision about data, the rows grant
--      nothing once item 3 and the two API-side changes in the same commit apply, and the count is what the owner needs.
--
--   THE API-SIDE READERS CHANGE WITH IT (the migration's tests cannot see them): `core/authz.assigned_client_ids`,
--   `is_client_assigned` and `core/auth._permission_overrides` read the same two tables with the privileged client and no
--   firm, so a row already planted would have kept granting through every route while the database ignored it. They filter
--   on the member's firm now, and `assignment_repository.create` looks for an existing (user, client) pair in the caller's
--   firm only, so a planted row of another firm is not reported to a Partner as the assignment they just asked for.
--
--   Nothing a Partner does for their own firm changes, and nothing an assigned member sees changes: every row the API writes
--   already names a member and a client of the caller's firm.
--
-- WHAT IT LEAVES ALONE, AND SAYS SO
--
--   * The same missing check on every other table that has a `client_id` and a `firm_id` (a row whose client belongs to
--     another firm than its own) and on the other tables that name a member: POST-A-304.
--   * A planted row also occupies the table's unique key on (user_id, client_id) or (user_id, resource, action), and only
--     the other firm's Partner can delete it. It grants nothing now, and it is counted in the warning; whether to delete the
--     ones that exist is decided from that count.
--   * The database lets a Partner assign a non-Partner to the firm's internal practice client, which the API refuses (G1);
--     that is not a cross-firm hole and is recorded under POST-A-306.
--   * The SELECT policies of both tables, 478's reason stands (the caller's own rows are read under their own sign-in); a
--     planted row has the other firm's id, so a member of F never sees it there.
--
-- Idempotent (CREATE OR REPLACE, ALTER POLICY). Reversible: 530_..._rollback.sql restores the three functions and the three
-- policies exactly and drops the helpers, which RE-OPENS the hole. A lock_timeout of 15 seconds for this transaction (as 525
-- to 529 set) makes a long-running transaction that holds either table fail the migration, to be re-run, instead of queueing
-- every later request on it.

SELECT set_config('lock_timeout', '15s', true);

-- ── 1. the two helpers ──────────────────────────────────────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.user_is_in_my_firm(p_user_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.users u
     WHERE u.id = p_user_id
       AND u.firm_id = public.get_my_firm_id()
  )
$$;

CREATE OR REPLACE FUNCTION public.client_is_in_my_firm(p_client_id uuid)
RETURNS boolean
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT EXISTS (
    SELECT 1 FROM public.clients c
     WHERE c.id = p_client_id
       AND c.firm_id = public.get_my_firm_id()
  )
$$;

REVOKE ALL ON FUNCTION public.user_is_in_my_firm(uuid) FROM PUBLIC, anon;
REVOKE ALL ON FUNCTION public.client_is_in_my_firm(uuid) FROM PUBLIC, anon;
GRANT EXECUTE ON FUNCTION public.user_is_in_my_firm(uuid) TO authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.client_is_in_my_firm(uuid) TO authenticated, service_role;

-- ── 2. the write policies ask the member, and the client ────────────────────────────────────────────────────────────

ALTER POLICY "partners_insert_assignments" ON public.user_client_assignments
  WITH CHECK (
    firm_id = (SELECT public.get_my_firm_id())
    AND (SELECT public.my_permission('assignment', 'write', 'Partner'))
    AND (SELECT public.user_is_in_my_firm(user_id))
    AND (SELECT public.client_is_in_my_firm(client_id))
  );

ALTER POLICY "partners_update_assignments" ON public.user_client_assignments
  WITH CHECK (
    firm_id = (SELECT public.get_my_firm_id())
    AND (SELECT public.my_permission('assignment', 'write', 'Partner'))
    AND (SELECT public.user_is_in_my_firm(user_id))
    AND (SELECT public.client_is_in_my_firm(client_id))
  );

ALTER POLICY "firm_user_permissions" ON public.user_permissions
  WITH CHECK (
    firm_id = (SELECT public.get_my_firm_id())
    AND (SELECT public.user_is_in_my_firm(user_id))
  );

-- ── 3. a row that names the wrong firm grants nothing ───────────────────────────────────────────────────────────────

CREATE OR REPLACE FUNCTION public.my_assigned_client_ids()
RETURNS SETOF text
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT a.client_id::text
    FROM public.user_client_assignments a
    JOIN public.clients c ON c.id = a.client_id AND c.firm_id = a.firm_id
   WHERE a.user_id = (SELECT public.get_my_user_id())
     AND a.firm_id = (SELECT public.get_my_firm_id())
$$;

CREATE OR REPLACE FUNCTION public.can_access_client(p_client_id text)
RETURNS boolean
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public
AS $$
  SELECT
    p_client_id IS NULL
    OR COALESCE(public.get_my_role() = 'Partner', FALSE)
    OR EXISTS (
      SELECT 1
        FROM public.user_client_assignments a
        JOIN public.clients c ON c.id = a.client_id AND c.firm_id = a.firm_id
       WHERE a.user_id = public.get_my_user_id()
         AND a.firm_id = public.get_my_firm_id()
         AND a.client_id::text = p_client_id
    );
$$;

CREATE OR REPLACE FUNCTION public.my_permission(
  resource      text,
  action        text,
  minimum_role  text
)
RETURNS boolean
LANGUAGE plpgsql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
DECLARE
  v_granted boolean;
BEGIN
  -- The person's own answer, if they have one. `granted` is NOT NULL and the
  -- ROW is what is optional, so "no opinion" has exactly one spelling and a
  -- NULL here means only that no row was found — which is also what a member
  -- who is no longer live gets, because get_my_user_id() is NULL for them.
  -- A row counts only if it was written in the member's own firm (530).
  SELECT up.granted
    INTO v_granted
    FROM public.user_permissions up
   WHERE up.user_id = public.get_my_user_id()
     AND up.firm_id = public.get_my_firm_id()
     AND up.resource = my_permission.resource
     AND up.action   = my_permission.action
   LIMIT 1;

  IF v_granted IS NULL THEN
    -- No row: the role decides, at the minimum this policy names.
    RETURN public.my_role_at_least(minimum_role);
  END IF;

  IF v_granted IS FALSE
     AND public.role_rank(public.get_my_role()) >= public.role_rank('Partner')
     AND (my_permission.resource, my_permission.action) IN
         (('team','read'), ('team','write'), ('firm','read'), ('firm','admin'))
  THEN
    -- A Partner keeps the four pairs that reach the access screen itself,
    -- whatever the grid says. See migration 415's header.
    RETURN true;
  END IF;

  RETURN v_granted;
END;
$$;

-- ── 4. how many rows are already wrong ──────────────────────────────────────────────────────────────────────────────

DO $$
DECLARE
  n_assign bigint;
  n_perm bigint;
BEGIN
  SELECT count(*) INTO n_assign
    FROM public.user_client_assignments a
   WHERE NOT EXISTS (SELECT 1 FROM public.users u WHERE u.id = a.user_id AND u.firm_id = a.firm_id)
      OR NOT EXISTS (SELECT 1 FROM public.clients c WHERE c.id = a.client_id AND c.firm_id = a.firm_id);
  SELECT count(*) INTO n_perm
    FROM public.user_permissions p
   WHERE NOT EXISTS (SELECT 1 FROM public.users u WHERE u.id = p.user_id AND u.firm_id = p.firm_id);
  RAISE WARNING 'migration 530: % assignment row(s) and % permission row(s) name a member or a client of another firm than their own; they grant nothing from now on and are not removed', n_assign, n_perm;
END
$$;
