-- 089_platform_purge.sql
-- Platform Admin: permanent (hard) firm deletion + durable platform audit trail.
--
-- Soft-delete (088/router) only sets deleted_at + is_active=false. This adds an
-- IRREVERSIBLE purge for removing test/abandoned firms entirely. It is exposed
-- only through the platform router behind require_platform_admin_mfa (aal2), so
-- it can never be reached by firm RBAC.
--
-- The firm graph has mixed FK rules (CASCADE on some, NO ACTION on ~39 tables),
-- so a plain `delete from firms` would be blocked. The function disables FK
-- enforcement for the duration of its own transaction (session_replication_role
-- = replica) and removes every firm-scoped row, so deletion order can't block.
-- It deliberately does NOT touch auth.users — the login accounts (and the
-- platform admin's own allowlist entry) survive a purge of their firm.

-- ── Durable platform-level audit (NOT firm-scoped, so it outlives a purge) ────
-- Uses target_firm_id (not firm_id) on purpose: the purge function sweeps every
-- table that has a `firm_id` column, and this record must NOT be swept away.
create table if not exists platform_audit (
  id                  uuid primary key default gen_random_uuid(),
  action              text not null,
  target_firm_id      uuid,
  firm_name           text,
  actor_auth_user_id  uuid,
  actor_email         text,
  metadata            jsonb not null default '{}'::jsonb,
  created_at          timestamptz not null default now()
);
alter table platform_audit enable row level security;
-- service-role only (no policy = deny to anon/authenticated under RLS)
revoke all on platform_audit from anon, authenticated;

-- ── platform_purge_firm: hard-delete a firm and all firm-scoped data ─────────
create or replace function platform_purge_firm(p_firm_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  r           record;
  v_clients   uuid[];
  v_client_n  int;
  v_user_n    int;
begin
  if p_firm_id is null then
    raise exception 'firm id required';
  end if;

  select array_agg(id) into v_clients from clients where firm_id = p_firm_id;
  v_client_n := coalesce(array_length(v_clients, 1), 0);
  select count(*) into v_user_n from users where firm_id = p_firm_id;

  -- Disable FK enforcement + triggers for THIS transaction only, so the mixed
  -- CASCADE / NO ACTION constraints can't block the deletion order.
  set local session_replication_role = 'replica';

  -- 1) Every firm-scoped base table (has a firm_id column). This covers clients,
  --    users, audit_logs and all firm-owned data in one sweep.
  for r in
    select c.table_name
    from information_schema.columns c
    join information_schema.tables t
      on t.table_schema = c.table_schema and t.table_name = c.table_name
     and t.table_type = 'BASE TABLE'
    where c.table_schema = 'public' and c.column_name = 'firm_id'
  loop
    execute format('delete from public.%I where firm_id = $1', r.table_name) using p_firm_id;
  end loop;

  -- 2) Grandchildren scoped only by client_id (no firm_id of their own).
  if v_client_n > 0 then
    for r in
      select c.table_name
      from information_schema.columns c
      join information_schema.tables t
        on t.table_schema = c.table_schema and t.table_name = c.table_name
       and t.table_type = 'BASE TABLE'
      where c.table_schema = 'public' and c.column_name = 'client_id'
    loop
      execute format('delete from public.%I where client_id = any($1)', r.table_name) using v_clients;
    end loop;
  end if;

  -- 3) Core rows. clients/users carry firm_id (handled in step 1); the firm row
  --    itself has no firm_id column, so remove it explicitly. Defensive re-deletes
  --    are harmless.
  delete from clients where firm_id = p_firm_id;
  delete from users   where firm_id = p_firm_id;
  delete from firms   where id = p_firm_id;

  return jsonb_build_object(
    'firm_id', p_firm_id,
    'clients_deleted', v_client_n,
    'users_deleted', v_user_n
  );
end;
$$;

revoke all on function platform_purge_firm(uuid) from anon, authenticated;

-- Rollback:
--   drop function if exists platform_purge_firm(uuid);
--   drop table if exists platform_audit;
