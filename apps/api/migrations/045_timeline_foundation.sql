-- Migration 045: Timeline Foundation
-- Creates the append-only client_timeline_events table per Product Bible v1.0 Chapter 9

do $$ begin
  create type event_category as enum (
    'accounting', 'compliance', 'payroll', 'tax',
    'document', 'work', 'ai', 'portal', 'team'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type event_severity as enum ('info', 'success', 'warning', 'critical');
exception when duplicate_object then null; end $$;

do $$ begin
  create type event_actor_type as enum ('user', 'system', 'ai', 'client');
exception when duplicate_object then null; end $$;

do $$ begin
  create type event_visibility as enum ('all', 'internal', 'partner_only');
exception when duplicate_object then null; end $$;

create table if not exists client_timeline_events (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references clients(id) on delete cascade,
  firm_id         uuid not null references firms(id) on delete cascade,
  financial_year  text not null,
  period          text,                          -- e.g. '2025-06' for monthly events

  -- Categorisation
  category        event_category not null,
  event_type      text not null,                 -- granular type within category
  severity        event_severity not null default 'info',

  -- Human-readable content
  title           text not null,                 -- 1-line summary
  description     text,                          -- 2-3 line detail
  action_label    text,                          -- CTA text e.g. "Review in Compliance"
  action_url      text,                          -- relative URL for CTA

  -- Source record linking
  entity_type     text,                          -- 'work_item' | 'journal_entry' | etc.
  entity_id       uuid,

  -- Actor
  actor_type      event_actor_type not null default 'system',
  actor_id        uuid,
  actor_name      text,                          -- denormalised for display

  -- Financial context
  amount_paise    bigint,                        -- integer paise only, never float

  -- Display
  is_pinned       boolean not null default false,
  visibility      event_visibility not null default 'all',

  -- Audit — append-only, soft-delete only
  created_at      timestamptz not null default now(),
  deleted_at      timestamptz,
  deleted_by      uuid
);

-- Row Level Security — firm isolation
alter table client_timeline_events enable row level security;

drop policy if exists "firm_isolation" on client_timeline_events;
create policy "firm_isolation" on client_timeline_events
  for all using (firm_id = (select get_my_firm_id()));

-- Performance indexes
create index if not exists idx_timeline_client_date
  on client_timeline_events (client_id, created_at desc)
  where deleted_at is null;

create index if not exists idx_timeline_client_category
  on client_timeline_events (client_id, category, created_at desc)
  where deleted_at is null;

create index if not exists idx_timeline_client_fy
  on client_timeline_events (client_id, financial_year, created_at desc)
  where deleted_at is null;

create index if not exists idx_timeline_entity
  on client_timeline_events (entity_type, entity_id)
  where entity_id is not null;

-- Grants
grant select, insert, update on client_timeline_events to authenticated;
grant all on client_timeline_events to service_role;
