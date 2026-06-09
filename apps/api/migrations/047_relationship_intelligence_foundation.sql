-- Migration 047: Relationship Intelligence Foundation
-- Creates entity graph tables per Product Bible v1.0 Chapter 9

do $$ begin
  create type entity_kind as enum (
    'individual', 'company', 'llp', 'partnership', 'trust', 'huf', 'other'
  );
exception when duplicate_object then null; end $$;

do $$ begin
  create type relationship_kind as enum (
    'director', 'shareholder', 'partner', 'trustee', 'beneficiary',
    'proprietor', 'guarantor', 'authorized_signatory', 'related_party', 'group_company'
  );
exception when duplicate_object then null; end $$;

-- Canonical entity registry (people / organisations across clients)
create table if not exists ri_entities (
  id              uuid primary key default gen_random_uuid(),
  firm_id         uuid not null references firms(id) on delete cascade,

  kind            entity_kind not null,
  display_name    text not null,

  -- Identity documents (nullable — filled as discovered)
  pan             text,
  gstin           text,
  din             text,                            -- Director Identification Number
  aadhaar_last4   text,                            -- last 4 digits only, never full

  -- Contact
  email           text,
  phone           text,

  -- Metadata
  is_verified     boolean not null default false,
  merged_into     uuid references ri_entities(id), -- soft-merge: point to canonical entity

  created_at      timestamptz not null default now(),
  updated_at      timestamptz not null default now()
);

create index if not exists idx_ri_entities_firm
  on ri_entities (firm_id);
create index if not exists idx_ri_entities_pan
  on ri_entities (firm_id, pan)
  where pan is not null;

alter table ri_entities enable row level security;
drop policy if exists "firm_isolation" on ri_entities;
create policy "firm_isolation" on ri_entities
  for all using (firm_id = (select get_my_firm_id()));

-- Relationships between clients and entities
create table if not exists ri_client_entity_links (
  id              uuid primary key default gen_random_uuid(),
  firm_id         uuid not null references firms(id) on delete cascade,
  client_id       uuid not null references clients(id) on delete cascade,
  entity_id       uuid not null references ri_entities(id) on delete cascade,

  relationship    relationship_kind not null,
  ownership_pct   numeric(5,2),                   -- for shareholders / partners
  effective_from  date,
  effective_to    date,                           -- null = currently active

  source          text,                           -- 'mca', 'manual', 'ai_extracted'
  notes           text,

  created_at      timestamptz not null default now()
);

create unique index if not exists idx_ri_client_entity_unique
  on ri_client_entity_links (client_id, entity_id, relationship)
  where effective_to is null;

create index if not exists idx_ri_client_entity_client
  on ri_client_entity_links (client_id);
create index if not exists idx_ri_client_entity_entity
  on ri_client_entity_links (entity_id);

alter table ri_client_entity_links enable row level security;
drop policy if exists "firm_isolation" on ri_client_entity_links;
create policy "firm_isolation" on ri_client_entity_links
  for all using (firm_id = (select get_my_firm_id()));

-- Relationships between entities (e.g. person A is director in company B)
create table if not exists ri_entity_relationships (
  id              uuid primary key default gen_random_uuid(),
  firm_id         uuid not null references firms(id) on delete cascade,

  from_entity_id  uuid not null references ri_entities(id) on delete cascade,
  to_entity_id    uuid not null references ri_entities(id) on delete cascade,
  relationship    relationship_kind not null,

  effective_from  date,
  effective_to    date,
  source          text,
  notes           text,

  created_at      timestamptz not null default now(),

  check (from_entity_id <> to_entity_id)
);

create index if not exists idx_ri_entity_rel_from
  on ri_entity_relationships (from_entity_id)
  where effective_to is null;
create index if not exists idx_ri_entity_rel_to
  on ri_entity_relationships (to_entity_id)
  where effective_to is null;

alter table ri_entity_relationships enable row level security;
drop policy if exists "firm_isolation" on ri_entity_relationships;
create policy "firm_isolation" on ri_entity_relationships
  for all using (firm_id = (select get_my_firm_id()));

-- Cross-client shared entity detection (same PAN appears in multiple clients)
create table if not exists ri_cross_client_signals (
  id              uuid primary key default gen_random_uuid(),
  firm_id         uuid not null references firms(id) on delete cascade,
  entity_id       uuid not null references ri_entities(id) on delete cascade,

  client_ids      uuid[] not null,                -- all clients where entity appears
  signal_type     text not null,                  -- 'shared_director', 'shared_pan', etc.
  detected_at     timestamptz not null default now(),
  dismissed_at    timestamptz,
  dismissed_by    uuid
);

alter table ri_cross_client_signals enable row level security;
drop policy if exists "firm_isolation" on ri_cross_client_signals;
create policy "firm_isolation" on ri_cross_client_signals
  for all using (firm_id = (select get_my_firm_id()));

-- Grants
grant select, insert, update on ri_entities to authenticated;
grant select, insert, update on ri_client_entity_links to authenticated;
grant select, insert, update on ri_entity_relationships to authenticated;
grant select, insert, update on ri_cross_client_signals to authenticated;
grant all on ri_entities, ri_client_entity_links, ri_entity_relationships, ri_cross_client_signals to service_role;
