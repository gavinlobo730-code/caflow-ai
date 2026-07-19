-- Migration 113: Compound indexes for /work page query patterns
--
-- The /work page runs three query patterns against tasks that lacked compound indexes:
--   1. getTasks(): WHERE firm_id = X ORDER BY created_at DESC
--   2. workload open tasks: WHERE firm_id = X AND status != 'completed'
--   3. workload completed-this-month: WHERE firm_id = X AND status = 'completed' AND updated_at >= month_start
--
-- A single-column idx_tasks_firm_id (migration 017) means Postgres fetches all firm
-- rows then re-sorts/filters in memory. At 10k tasks across a firm this becomes
-- a sequential scan on the filtered set. The compound indexes below let Postgres
-- satisfy each query with an index-only scan.
--
-- Also adds assignee_id index: the workload handler queries
--   SELECT ... FROM tasks WHERE firm_id = X
-- and then matches rows via assignee_id in Python. The existing idx_tasks_assigned
-- covers the older assigned_to column (UUID FK to team_members); assignee_id is
-- a separate column added later and has no index.

-- 1. (firm_id, created_at) — satisfies getTasks() ORDER BY created_at DESC
CREATE INDEX IF NOT EXISTS idx_tasks_firm_created
    ON public.tasks (firm_id, created_at DESC)
    WHERE deleted_at IS NULL;

-- 2. (firm_id, status) — satisfies workload open-tasks filter
CREATE INDEX IF NOT EXISTS idx_tasks_firm_status
    ON public.tasks (firm_id, status)
    WHERE deleted_at IS NULL;

-- 3. (firm_id, updated_at) — satisfies workload completed-this-month filter
CREATE INDEX IF NOT EXISTS idx_tasks_firm_updated
    ON public.tasks (firm_id, updated_at DESC)
    WHERE deleted_at IS NULL;

-- 4. assignee_id — workload Python join matches on this column
--    R2.6 fix: no earlier migration ever added this column (the comment above
--    was wrong — assignee_id was never created, only assumed). Every write/
--    read touching it has been failing with "column does not exist" since
--    Phase 1.2. Add it before indexing it, backfilled from the legacy
--    assigned_to FK so existing rows aren't orphaned.
ALTER TABLE public.tasks
    ADD COLUMN IF NOT EXISTS assignee_id UUID REFERENCES public.team_members(id);

UPDATE public.tasks SET assignee_id = assigned_to
    WHERE assignee_id IS NULL AND assigned_to IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_tasks_assignee_id
    ON public.tasks (assignee_id)
    WHERE deleted_at IS NULL;

-- 5. user_capacity (firm_id) — workload fetches capacity_map by firm
--    (may already exist; IF NOT EXISTS is safe)
CREATE INDEX IF NOT EXISTS idx_user_capacity_firm_id
    ON public.user_capacity (firm_id);

-- 6. time_entries (firm_id, started_at) — workload queries this week's entries
CREATE INDEX IF NOT EXISTS idx_time_entries_firm_started
    ON public.time_entries (firm_id, started_at DESC);
