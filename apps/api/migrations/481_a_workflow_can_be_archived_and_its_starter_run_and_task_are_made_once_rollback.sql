-- Rollback for 481 — a workflow template can be archived, and a starter, a run
-- and a step's task are each made once (POST-A-200, POST-A-204).
--
-- Dropping these columns FORGETS what was recorded in them, and each loss changes
-- what the product does:
--
--   * `workflow_templates.archived_at` — an archived template would become an
--     ordinary template again and, if it was left active, could fire;
--   * `workflow_templates.starter_key` — a starter would stop being recognised
--     as one, and installing the starters again would make a second copy beside
--     it;
--   * `tasks.workflow_instance_id` and `tasks.workflow_step_ref` — a task would
--     lose which run and step made it, and a re-run of that step would make the
--     task a second time.
--
-- So this REFUSES while any row holds a value in any of the four columns,
-- naming how many. To roll back deliberately: export what you need, clear the
-- columns yourself (UPDATE ... SET <column> = NULL), and run this again:
--   SELECT id, firm_id, starter_key, archived_at FROM public.workflow_templates
--    WHERE starter_key IS NOT NULL OR archived_at IS NOT NULL;
--   SELECT id, firm_id, workflow_instance_id, workflow_step_ref FROM public.tasks
--    WHERE workflow_instance_id IS NOT NULL OR workflow_step_ref IS NOT NULL;
--
-- Dropping the unique index on workflow_instances loses no data, but it puts the
-- race back: two requests can again both start the same run. Roll the code back
-- with this file: anything that names a column below fails on its first call
-- without it, and the engine's duplicate-start handling (23505 means "already
-- started") has nothing left to react to.
--
-- Re-runnable: each check asks whether the column exists before it counts.

BEGIN;

DO $$
DECLARE
  n_archived bigint := 0;
  n_starters bigint := 0;
  n_runs     bigint := 0;
  n_steps    bigint := 0;
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'workflow_templates'
               AND column_name = 'archived_at') THEN
    EXECUTE 'SELECT count(*) FROM public.workflow_templates WHERE archived_at IS NOT NULL'
       INTO n_archived;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'workflow_templates'
               AND column_name = 'starter_key') THEN
    EXECUTE 'SELECT count(*) FROM public.workflow_templates WHERE starter_key IS NOT NULL'
       INTO n_starters;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'tasks'
               AND column_name = 'workflow_instance_id') THEN
    EXECUTE 'SELECT count(*) FROM public.tasks WHERE workflow_instance_id IS NOT NULL'
       INTO n_runs;
  END IF;
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema = 'public' AND table_name = 'tasks'
               AND column_name = 'workflow_step_ref') THEN
    EXECUTE 'SELECT count(*) FROM public.tasks WHERE workflow_step_ref IS NOT NULL'
       INTO n_steps;
  END IF;

  IF n_archived + n_starters + n_runs + n_steps > 0 THEN
    RAISE EXCEPTION
      'Refusing to roll back 481: % archived template(s), % installed starter(s), % task(s) naming '
      'the run that made them and % task(s) naming the step. Dropping the columns would forget '
      'them (an archived template would be an ordinary one again, a starter would be installed a '
      'second time, and a re-run step would make its task twice). Export, clear the columns and '
      'run this again.', n_archived, n_starters, n_runs, n_steps;
  END IF;
END $$;

DROP INDEX IF EXISTS public.uq_tasks_workflow_step_once;
ALTER TABLE public.tasks DROP CONSTRAINT IF EXISTS tasks_workflow_step_ref_check;
ALTER TABLE public.tasks DROP COLUMN IF EXISTS workflow_step_ref;
ALTER TABLE public.tasks DROP COLUMN IF EXISTS workflow_instance_id;

DROP INDEX IF EXISTS public.uq_wf_instances_live_idempotency;

DROP INDEX IF EXISTS public.uq_wf_templates_firm_starter_key;
ALTER TABLE public.workflow_templates DROP CONSTRAINT IF EXISTS workflow_templates_starter_key_check;
ALTER TABLE public.workflow_templates DROP COLUMN IF EXISTS starter_key;
ALTER TABLE public.workflow_templates DROP COLUMN IF EXISTS archived_at;

COMMIT;
