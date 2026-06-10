-- Phase 1.2 completion: scheduler logging, invoice lifecycle, workload capacity

-- Scheduler run log: one row per job execution, used for idempotency + audit
create table if not exists scheduler_runs (
  id uuid primary key default gen_random_uuid(),
  job_name text not null,
  run_date date not null,
  firm_id uuid,
  status text not null default 'success', -- success | failed
  detail jsonb,
  started_at timestamptz not null default now(),
  finished_at timestamptz
);

create index if not exists idx_scheduler_runs_job_date on scheduler_runs (job_name, run_date);

-- Invoice lifecycle: payment due date (defaults to invoice_date + 30 days at generation time)
alter table fee_invoices add column if not exists due_date date;
create index if not exists idx_fee_invoices_status_due on fee_invoices (status, due_date);

-- Workload capacity: weekly capacity per user, configured by managers
create table if not exists user_capacity (
  id uuid primary key default gen_random_uuid(),
  firm_id uuid not null,
  user_id uuid not null,
  weekly_capacity_hours integer not null default 40,
  max_concurrent_tasks integer not null default 15,
  updated_by uuid,
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now(),
  unique (firm_id, user_id)
);

create index if not exists idx_user_capacity_firm on user_capacity (firm_id);
