-- Migration 019: Critical fix — get_my_firm_id() used wrong column
-- Migration 016 accidentally used id = auth.uid() instead of auth_user_id = auth.uid()
-- This caused get_my_firm_id() to return NULL for all users, breaking every RLS INSERT policy

CREATE OR REPLACE FUNCTION public.get_my_firm_id()
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = public, pg_catalog
AS $$
  SELECT firm_id FROM public.users WHERE auth_user_id = auth.uid() LIMIT 1;
$$;

REVOKE EXECUTE ON FUNCTION public.get_my_firm_id() FROM anon;
GRANT EXECUTE ON FUNCTION public.get_my_firm_id() TO authenticated;

-- Also allow Partners to insert invited users into their firm (no auth_user_id yet)
DROP POLICY IF EXISTS "partners_can_invite_users" ON public.users;
CREATE POLICY "partners_can_invite_users" ON public.users
  FOR INSERT TO authenticated
  WITH CHECK (
    firm_id = public.get_my_firm_id()
  );
