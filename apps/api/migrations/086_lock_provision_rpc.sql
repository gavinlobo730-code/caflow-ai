-- PracticeSync AI — Migration 086: lock down provision_internal_client RPC
-- Security hardening (advisor 0028/0029). provision_internal_client is a
-- SECURITY DEFINER provisioning helper — NOT an RLS helper and NOT called via
-- PostgREST RPC by the app (the backend provisions via the Python service using
-- the service-role key). It was executable by anon/authenticated only through the
-- default PUBLIC grant, which is an unnecessary attack surface. Revoke it; keep
-- service_role. Idempotent, reversible.
--
-- NOTE: the RLS-helper SECURITY DEFINER functions (can_access_client, get_my_role,
-- get_my_user_id, my_internal_client_id) are intentionally LEFT executable —
-- revoking EXECUTE from `authenticated` there would break the RLS policies that
-- call them.

REVOKE EXECUTE ON FUNCTION public.provision_internal_client(uuid, text, text, text, text)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.provision_internal_client(uuid, text, text, text, text)
  TO service_role;
