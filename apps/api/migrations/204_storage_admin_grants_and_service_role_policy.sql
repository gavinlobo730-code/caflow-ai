-- Migration 203 granted get_my_firm_id() EXECUTE to service_role, on the
-- assumption that a service-role-keyed Storage request runs its Postgres
-- queries AS the service_role role (which bypasses RLS outright, rolbypassrls
-- = true). That assumption is wrong for Supabase Storage specifically:
-- storage-api's own DB connection always executes as supabase_storage_admin
-- (rolbypassrls = false, confirmed live) regardless of which API key the
-- caller presents — it does NOT `SET ROLE` to the caller's JWT role the way
-- PostgREST does for /rest/v1/*. So the Documents bucket's RLS policies
-- (documents_storage_insert/select/delete, all keyed on get_my_firm_id())
-- were being evaluated AS supabase_storage_admin, which had never been
-- granted EXECUTE on get_my_firm_id() — confirmed live via Postgres logs
-- showing "permission denied for function get_my_firm_id" recurring on every
-- purchase-bill attachment upload attempt, unchanged before and after 203.
--
-- Two gaps, both fixed here:
--
-- 1. supabase_storage_admin lacked EXECUTE on every function the policies
--    touch (auth.uid(), auth.role(), get_my_firm_id()) and SELECT on
--    public.users (get_my_firm_id() queries it directly — it is not
--    SECURITY DEFINER, so the caller's own privileges apply).
--
-- 2. Even with those grants, get_my_firm_id() resolves via
--    `auth.uid()` -> `public.users.auth_user_id` — which is NULL for the
--    backend's own service-role-keyed uploads (that JWT has no `sub`, since
--    it isn't tied to a real end-user). So the firm-scoped policy can never
--    pass for backend-driven uploads, grants notwithstanding — a different
--    predicate is needed for that path. auth.role() reads the JWT's `role`
--    claim from session GUCs (independent of the literal executing Postgres
--    role), so it correctly identifies service-role-keyed requests even
--    though supabase_storage_admin is the role actually running the query.
--    New policies below grant the Documents bucket to any request whose JWT
--    claims role=service_role, matching this app's existing assumption
--    (core/supabase_client.py's docstring) that the service-role client
--    bypasses RLS — an assumption already true for ordinary tables via
--    rolbypassrls, extended here to Storage where that mechanism doesn't
--    reach.
GRANT EXECUTE ON FUNCTION auth.uid() TO supabase_storage_admin;
GRANT EXECUTE ON FUNCTION auth.role() TO supabase_storage_admin;
GRANT EXECUTE ON FUNCTION public.get_my_firm_id() TO supabase_storage_admin;
GRANT SELECT ON public.users TO supabase_storage_admin;

CREATE POLICY "documents_storage_service_role_insert" ON storage.objects
  FOR INSERT
  WITH CHECK (bucket_id = 'Documents' AND auth.role() = 'service_role');

CREATE POLICY "documents_storage_service_role_select" ON storage.objects
  FOR SELECT
  USING (bucket_id = 'Documents' AND auth.role() = 'service_role');

CREATE POLICY "documents_storage_service_role_delete" ON storage.objects
  FOR DELETE
  USING (bucket_id = 'Documents' AND auth.role() = 'service_role');
