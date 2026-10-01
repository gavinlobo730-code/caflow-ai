-- Rollback for 452. DISCARDS every task estimate recorded since it landed.
--
-- Roll the code back with this file: `routers/workload`, `capacity_risk_service`
-- and the task-creating doors name the column, so each fails on its first call
-- without it. The forecast then falls back to the old join through
-- `workflow_steps.estimated_hours`, which finds an estimate for almost nothing.

BEGIN;

ALTER TABLE public.tasks DROP CONSTRAINT IF EXISTS tasks_estimated_minutes_check;
ALTER TABLE public.tasks DROP COLUMN IF EXISTS estimated_minutes;

COMMIT;
