-- 090_platform_purge_typesafe.sql
-- Fix: platform_purge_firm compared *_id columns (some typed TEXT, e.g.
-- client_timeline_events.client_id) against uuid[] / uuid, raising
-- "operator does not exist: text = uuid" mid-purge. Compare ids AS TEXT so a
-- firm_id / client_id column typed as either uuid OR text matches. No behaviour
-- change other than the type-safe comparison.

create or replace function platform_purge_firm(p_firm_id uuid)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  r            record;
  v_client_ids text[];
  v_client_n   int;
  v_user_n     int;
begin
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
$$;

revoke all on function platform_purge_firm(uuid) from anon, authenticated;

-- Rollback: re-apply 089's version of platform_purge_firm.
