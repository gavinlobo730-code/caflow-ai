-- Rollback of migration 530: the three write policies and the three functions go back to the text migrations 478/525, 403/415
-- (firm_user_permissions), 526, 468 and 468 gave them, and the two helpers are dropped.
--
-- Rolling back RE-OPENS the hole 530 closes: a Partner of one firm can write an assignment or a permission that names a member
-- (and a client) of another firm, and `my_assigned_client_ids()`, `can_access_client()` and `my_permission()` honour it.

ALTER POLICY "partners_insert_assignments" ON public.user_client_assignments
  WITH CHECK (
    firm_id = (SELECT public.get_my_firm_id())
    AND (SELECT public.my_permission('assignment', 'write', 'Partner'))
  );

ALTER POLICY "partners_update_assignments" ON public.user_client_assignments
  WITH CHECK (
    firm_id = (SELECT public.get_my_firm_id())
    AND (SELECT public.my_permission('assignment', 'write', 'Partner'))
  );

ALTER POLICY "firm_user_permissions" ON public.user_permissions
  WITH CHECK (firm_id = (SELECT public.get_my_firm_id()));

CREATE OR REPLACE FUNCTION public.my_assigned_client_ids()
RETURNS SETOF text
LANGUAGE sql
STABLE SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $$
  SELECT a.client_id::text
    FROM public.user_client_assignments a
   WHERE a.user_id = public.get_my_user_id()
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
       WHERE a.user_id = public.get_my_user_id()
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
  SELECT up.granted
    INTO v_granted
    FROM public.user_permissions up
   WHERE up.user_id = public.get_my_user_id()
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

DROP FUNCTION IF EXISTS public.user_is_in_my_firm(uuid);
DROP FUNCTION IF EXISTS public.client_is_in_my_firm(uuid);
