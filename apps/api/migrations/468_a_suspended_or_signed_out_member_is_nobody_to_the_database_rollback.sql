-- Rollback for migration 468: put the five functions back as 019 / 073+144 /
-- 079+144 / 084 / 415 left them, then drop the rule they shared.
--
-- Rolling back RE-OPENS the hole 468 closes: a suspended member's JWT is
-- honoured by every RLS policy again until it expires.

CREATE OR REPLACE FUNCTION public.get_my_firm_id()
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT firm_id FROM public.users WHERE auth_user_id = auth.uid() LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.get_my_role()
RETURNS text
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT role FROM users WHERE auth_user_id = auth.uid() LIMIT 1;
$$;

CREATE OR REPLACE FUNCTION public.get_my_user_id()
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT id FROM users WHERE auth_user_id = auth.uid() LIMIT 1;
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
    OR public.get_my_role() = 'Partner'
    OR EXISTS (
      SELECT 1
      FROM public.user_client_assignments a
      JOIN public.users u ON u.id = a.user_id
      WHERE u.auth_user_id = auth.uid()
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
  SELECT up.granted
    INTO v_granted
    FROM public.user_permissions up
    JOIN public.users u ON u.id = up.user_id
   WHERE u.auth_user_id = auth.uid()
     AND up.resource = my_permission.resource
     AND up.action   = my_permission.action
   LIMIT 1;

  IF v_granted IS NULL THEN
    RETURN public.my_role_at_least(minimum_role);
  END IF;

  IF v_granted IS FALSE
     AND public.role_rank(public.get_my_role()) >= public.role_rank('Partner')
     AND (my_permission.resource, my_permission.action) IN
         (('team','read'), ('team','write'), ('firm','read'), ('firm','admin'))
  THEN
    RETURN true;
  END IF;

  RETURN v_granted;
END;
$$;

DROP FUNCTION IF EXISTS public.staff_session_is_live(boolean, timestamptz);
