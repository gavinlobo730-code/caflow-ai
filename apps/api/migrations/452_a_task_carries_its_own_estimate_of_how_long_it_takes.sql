-- ============================================================================
-- 452 — a task carries its own estimate of how long it takes
--      (practice_management-24)
--
-- WHY
--     The product held two answers to "how loaded is this person" and one of
--     them was a guess by job title (`/team/work-allocation` divided a count of
--     open tasks by a per-role constant in the browser). The other,
--     `/team/workload`, is a real model — a thirteen-week forecast off each
--     person's `weekly_capacity_hours` and the time they have logged — and it
--     could see effort for almost nothing, because a task row carried no
--     estimate. The only effort it could find was
--     `workflow_steps.estimated_hours`, reached through a `workflow_step_id` that
--     no door in the product writes, so the forecast reported "no effort
--     estimates recorded" for practically every firm; and a task made from a
--     template did not take the template's `estimated_hours`.
--
-- WHAT THIS ADDS
--     `tasks.estimated_minutes` — whole minutes, MORE than zero, or NULL.
--     Every door that makes a task from something that knows how long it takes
--     copies it at creation (`domain/practice/task_estimate` is the rule), so the
--     figure the forecast reads and the figure on the task are one figure and a
--     later edit to a template does not re-estimate work already made.
--
--     NULL MEANS "NOBODY ESTIMATED THIS" AND IS NEVER 0. There is no estimate of
--     nothing — a task that takes no time is not a task — and a stored 0 would
--     make a firm's work look free in exactly the forecast that exists to say it
--     is not. The CHECK is `> 0` for that reason, and it also stops a browser that
--     writes `tasks` straight over PostgREST (`lib/data/tasks.createTask` does)
--     from storing a 0 the API would have refused.
--
--     NO DEFAULT AND NO BACKFILL. Every existing task was made with nobody having
--     estimated it; filling a number in would assert a fact nobody holds, and the
--     forecast COUNTS the tasks that carry none beside the hours it can total
--     rather than averaging over them. The old join through `workflow_step_id`
--     stays as a fallback in `capacity_risk_service` for a task that has a step
--     and no estimate of its own, so nothing the forecast could already see is
--     lost.
--
-- WHAT IT DELIBERATELY DOES NOT DO
--     It adds no estimate to a compliance OBLIGATION. `compliance_calendar` rows
--     that are worked as a task are already counted once, as that task, and so
--     now carry the task's estimate; one that is not has nobody who has said how
--     long a GSTR-3B takes for this client, and a per-filing-type figure would be
--     one the firm records (a table and a screen of its own), not one this
--     migration can invent.
--
-- Additive and idempotent. No data is rewritten and no policy is touched — the
-- column rides on `tasks`' own RLS.
-- ============================================================================

BEGIN;

ALTER TABLE public.tasks
    ADD COLUMN IF NOT EXISTS estimated_minutes integer;

DO $$ BEGIN
  IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = 'public.tasks'::regclass
        AND conname  = 'tasks_estimated_minutes_check') THEN
    ALTER TABLE public.tasks
      ADD CONSTRAINT tasks_estimated_minutes_check
      CHECK (estimated_minutes IS NULL OR estimated_minutes > 0);
  END IF;
END $$;

COMMENT ON COLUMN public.tasks.estimated_minutes IS
    'How long this task is expected to take, in whole minutes (> 0), or NULL when '
    'nobody has estimated it (NULL is not 0). Copied at creation from the template '
    'or workflow step it was made from. Read by services/capacity_risk_service for '
    'the forecast and by GET /api/workload per person. Migration 452.';

COMMIT;
