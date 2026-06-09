-- Migration 046: Health Engine Foundation
-- Creates health score history and override tables per Product Bible v1.0 Chapter 9

create table if not exists client_health_scores (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references clients(id) on delete cascade,
  firm_id         uuid not null references firms(id) on delete cascade,
  financial_year  text not null,

  -- Composite score (0–100)
  overall_score   smallint not null check (overall_score between 0 and 100),

  -- Dimension scores (0–100 each)
  compliance_score     smallint not null default 0 check (compliance_score between 0 and 100),
  accounting_score     smallint not null default 0 check (accounting_score between 0 and 100),
  responsiveness_score smallint not null default 0 check (responsiveness_score between 0 and 100),
  document_score       smallint not null default 0 check (document_score between 0 and 100),
  financial_score      smallint not null default 0 check (financial_score between 0 and 100),

  -- Signals that drove the score (jsonb array of {signal, weight, value, label})
  signals         jsonb not null default '[]',

  -- Trend vs previous period
  trend           text check (trend in ('improving', 'stable', 'declining')),
  delta           smallint,                         -- score change vs previous snapshot

  -- Snapshot metadata
  computed_at     timestamptz not null default now(),
  snapshot_period text not null,                   -- 'YYYY-MM' of the snapshot

  -- Audit
  created_at      timestamptz not null default now()
);

-- Only one snapshot per client per period
create unique index if not exists idx_health_scores_unique_period
  on client_health_scores (client_id, financial_year, snapshot_period);

-- RLS — firm isolation
alter table client_health_scores enable row level security;
drop policy if exists "firm_isolation" on client_health_scores;
create policy "firm_isolation" on client_health_scores
  for all using (firm_id = (select get_my_firm_id()));

-- Performance indexes
create index if not exists idx_health_scores_client_date
  on client_health_scores (client_id, computed_at desc);

create index if not exists idx_health_scores_firm_overall
  on client_health_scores (firm_id, overall_score, computed_at desc);

-- Manual overrides table (CA can nudge a score with a reason)
create table if not exists client_health_overrides (
  id              uuid primary key default gen_random_uuid(),
  client_id       uuid not null references clients(id) on delete cascade,
  firm_id         uuid not null references firms(id) on delete cascade,
  financial_year  text not null,
  snapshot_period text not null,

  dimension       text not null,                   -- 'overall' | dimension name
  override_score  smallint not null check (override_score between 0 and 100),
  reason          text not null,

  created_by      uuid not null,
  created_at      timestamptz not null default now(),
  expires_at      timestamptz                      -- null = permanent until next compute
);

alter table client_health_overrides enable row level security;
drop policy if exists "firm_isolation" on client_health_overrides;
create policy "firm_isolation" on client_health_overrides
  for all using (firm_id = (select get_my_firm_id()));

-- Grants
grant select, insert on client_health_scores to authenticated;
grant select, insert, update, delete on client_health_overrides to authenticated;
grant all on client_health_scores, client_health_overrides to service_role;
