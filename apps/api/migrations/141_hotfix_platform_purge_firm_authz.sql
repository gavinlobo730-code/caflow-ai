-- Migration 141: P0 SECURITY HOTFIX — platform_purge_firm authorization (audit C7)
--
-- ROOT CAUSE
--   platform_purge_firm (SECURITY DEFINER; irreversibly deletes an entire firm and
--   all of its data) was executable by anon/authenticated through the INHERITED
--   PUBLIC EXECUTE grant. Migrations 089/090 ran `REVOKE ... FROM anon, authenticated`,
--   but those roles never held a DIRECT grant — their EXECUTE came from PUBLIC — so
--   the revoke was a no-op and PUBLIC (hence anon + authenticated) kept EXECUTE.
--   Verified against the live ACL (proacl carried an explicit PUBLIC=X entry). The
--   correct fix is to REVOKE ... FROM PUBLIC.
--
-- DEFENSE IN DEPTH — two independent layers, neither trusted alone:
--   (1) SQL grants: only the backend service_role may EXECUTE the RPC.
--   (2) In-body authorization: the function itself refuses unless the caller is the
--       trusted backend (service_role — already gated behind require_platform_admin_mfa
--       in routers/platform.py) OR a directly-authenticated platform administrator.
--       So even if EXECUTE is mistakenly re-granted later, unauthorized callers still
--       cannot purge a firm.
--
-- The delete logic below is byte-for-byte unchanged from the prior definition; the
-- only additions are the search_path pin and the authorization guard at the top.

CREATE OR REPLACE FUNCTION public.platform_purge_firm(p_firm_id uuid)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path TO 'public', 'pg_catalog'
AS $function$
declare
  r            record;
  v_client_ids text[];
  v_client_n   int;
  v_user_n     int;
begin
  -- (2) Defense-in-depth authorization, independent of the SQL EXECUTE grant.
  -- service_role  = the backend, already gated by platform-admin + MFA in the router.
  -- authenticated = allowed ONLY if the caller is in the platform_admins allowlist.
  -- anon / ordinary authenticated users are always refused.
  if coalesce(auth.role(), '') <> 'service_role'
     and not exists (
       select 1 from public.platform_admins pa where pa.auth_user_id = auth.uid()
     )
  then
    raise exception 'platform_purge_firm: not authorized — platform administrator required'
      using errcode = '42501';   -- insufficient_privilege
  end if;

  if p_firm_id is null then
    raise exception 'firm id required';
  end if;

  -- Compare ids as text so a *_id column typed as either uuid OR text matches.
  select array(select id::text from clients where firm_id = p_firm_id) into v_client_ids;
  v_client_n := coalesce(array_length(v_client_ids, 1), 0);
  select count(*) into v_user_n from users where firm_id = p_firm_id;

  set local session_replication_role = 'replica';

  for r in
    select c.table_name from information_schema.columns c
    join information_schema.tables t
      on t.table_schema = c.table_schema and t.table_name = c.table_name and t.table_type = 'BASE TABLE'
    where c.table_schema = 'public' and c.column_name = 'firm_id'
  loop
    execute format('delete from public.%I where firm_id::text = $1', r.table_name) using p_firm_id::text;
  end loop;

  if v_client_n > 0 then
    for r in
      select c.table_name from information_schema.columns c
      join information_schema.tables t
        on t.table_schema = c.table_schema and t.table_name = c.table_name and t.table_type = 'BASE TABLE'
      where c.table_schema = 'public' and c.column_name = 'client_id'
    loop
      execute format('delete from public.%I where client_id::text = any($1)', r.table_name) using v_client_ids;
    end loop;
  end if;

  delete from clients where firm_id = p_firm_id;
  delete from users   where firm_id = p_firm_id;
  delete from firms   where id = p_firm_id;

  return jsonb_build_object('firm_id', p_firm_id, 'clients_deleted', v_client_n, 'users_deleted', v_user_n);
end;
$function$;

-- (1) Remove the inherited PUBLIC grant (the actual bug) plus any anon/authenticated
-- grants; grant EXECUTE to the backend service_role only.
REVOKE ALL ON FUNCTION public.platform_purge_firm(uuid) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.platform_purge_firm(uuid) TO service_role;

-- Same inherited-PUBLIC exposure on the audit trigger functions: they are invoked by
-- triggers (which do NOT require the caller to hold EXECUTE) and must never be
-- RPC-callable. Removing the PUBLIC/anon/authenticated EXECUTE surface does not affect
-- auditing — trigger firing is independent of these grants.
REVOKE ALL ON FUNCTION public.audit_capture()      FROM PUBLIC, anon, authenticated;
REVOKE ALL ON FUNCTION public.audit_capture_firm() FROM PUBLIC, anon, authenticated;
