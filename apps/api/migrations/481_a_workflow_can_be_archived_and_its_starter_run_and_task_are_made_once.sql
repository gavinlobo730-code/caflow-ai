-- ============================================================================
-- 481 — a workflow template can be archived, and a starter, a run and a step's
--       task are each made ONCE  (POST-A-200, POST-A-204: schema only)
--
-- WHY
--     The workflow builder and the workflow engine both need four facts the
--     schema could not hold, and both would otherwise have shipped a migration
--     of their own that contradicted the other's:
--
--       * a template that has run cannot be deleted (`workflow_instances.template_id`
--         is a foreign key with no cascade, so DELETE is a 500), and "forget this
--         template" is a decision a CA makes for a template with history. It needs
--         an ARCHIVED state, not a delete;
--       * the six CA starter workflows are installed per firm, by an explicit
--         action and for a new firm. Pressing Install twice, or installing while
--         a second tab does the same, must leave six templates, not twelve — and
--         the database, not the click, is where that has to be true;
--       * a trigger that fires twice (two tabs, a scheduler tick and a manual
--         press, a retried request) must make ONE run. `check_idempotency` is
--         read-then-insert behind a plain index (157's `idx_wf_instances_idem`),
--         so two requests can both read "none" and both insert; and a later
--         read of that key then finds two rows and `maybe_single()` raises on
--         every start of that workflow afterwards;
--       * a step that creates a task must find its own task when it is run
--         again (a retry after a partial failure), instead of making another.
--         `tasks.workflow_id` and `tasks.workflow_step_id` cannot hold that:
--         the first references the LEGACY `workflows` table (002) and cannot
--         carry a template or instance id, and the second references
--         `workflow_steps(id)`, whose rows `update_template` deletes and
--         re-inserts with NEW ids — so a foreign key there would block the very
--         edit, and a stored id would dangle after it.
--
--     The two scouts that needed these (the builder's WF-4a and the engine's
--     PR-5) each designed the same instance index and DISAGREED about it: one
--     STATUS-BLIND, one status-aware. A status-blind unique key makes the retry
--     the engine promises impossible — a failed run's retry is a second row
--     with the same key — so this migration holds the reconciled one.
--
-- WHAT THIS ADDS (every column nullable, no default, no backfill)
--
--   workflow_templates.archived_at  timestamptz
--       NULL = not archived (every template that exists). Set = hidden from the
--       list unless asked for, never startable, never fired. It deliberately
--       does NOT imply `is_active = false` in the database: archiving is two
--       writes by one code path, and a CHECK here would make every writer order
--       them. The code that archives sets both, and the engine's firing filter
--       asks `archived_at IS NULL` itself.
--
--   workflow_templates.starter_key  text
--       NULL = a firm-made template (every template that exists). A value names
--       WHICH of the six starters the row is a copy of. Free text, validated in
--       Python the way the permission pair is (the vocabulary of starters moves
--       with the code and SQL cannot read a Python dict), so the only rules held
--       here are the ones that keep the unique key meaningful: no blank, no
--       surrounding whitespace, at most 100 characters.
--       UNIQUE (firm_id, starter_key): a starter is installed once per firm.
--       ARCHIVING A STARTER DOES NOT FREE ITS KEY — restoring it is the way
--       back, and a DUPLICATE of a starter is a firm-made template, so the code
--       that duplicates must write NULL here. The index is NOT partial, and that
--       is a choice, not an omission: NULLs are distinct in a unique index, so
--       every firm-made row still coexists, and a plain unique index is the one
--       `INSERT ... ON CONFLICT (firm_id, starter_key) DO NOTHING` can name as
--       its arbiter. PostgREST's upsert (`on_conflict=firm_id,starter_key` with
--       ignore-duplicates) cannot carry an index predicate, so a PARTIAL index
--       would force the installer into one insert per starter and a 23505 catch,
--       when the installer is meant to be two bulk inserts so signing up does not
--       gain dozens of Singapore-to-Mumbai round trips.
--
--   workflow_instances: UNIQUE (firm_id, template_id, idempotency_key)
--                       WHERE idempotency_key IS NOT NULL
--                         AND status NOT IN ('failed', 'cancelled')
--       One LIVE run per firm, template and key. A run that FAILED or was
--       CANCELLED does not hold its key, so the explicit retry (a new run with
--       the same key) is allowed, and nothing is ever silently re-fired: the
--       key is released only by a run having ended without finishing its work.
--       A completed run keeps it — the same event processed again is the thing
--       this exists to refuse. A row with no key (a caller that passes none) is
--       outside the index.
--       The key already includes the trigger type (SHA-256 of firm, trigger,
--       client and trigger data), which is why `trigger_event` is not a column
--       of the index.
--       THIS INDEX CANNOT BE AN ON CONFLICT ARBITER through PostgREST (it is
--       partial), so the code that creates a run treats SQLSTATE 23505 as "a
--       live run with this key already exists" and reads it back.
--       ⚠ A retry that flips the SAME failed row back to `pending` re-enters the
--       index, and is refused (23505) if a live run with that key was made in
--       the meantime; the code must read first and say so in words.
--
--   tasks.workflow_instance_id  uuid  REFERENCES workflow_instances(id)
--                                     ON DELETE SET NULL
--   tasks.workflow_step_ref     text
--       Which run, and which step of it, made this task. `workflow_step_ref` is
--       text because it holds a STEP KEY (or a step id taken from the run's own
--       snapshot), and neither is a foreign key for the reason above. SET NULL:
--       deleting a run must not delete or block the work it created.
--       UNIQUE (firm_id, workflow_instance_id, workflow_step_ref) WHERE both
--       are NOT NULL: one task per step per run, EVER — a soft-deleted task
--       still holds its slot, so a retry after somebody deleted the task finds
--       it (the code looks up INCLUDING deleted rows) instead of re-creating
--       work a person removed. `firm_id` leads the key so a task naming another
--       firm's run cannot take that firm's slot; it also serves the lookups the
--       code makes (firm, run) and (firm, run, step). Partial, so it cannot be
--       an ON CONFLICT arbiter: the step looks its task up first and treats
--       23505 as "already made".
--       No both-or-neither CHECK: the foreign key's own SET NULL would have to
--       null both columns, and a CHECK that forbids the state the action
--       produces would turn a harmless delete into an error.
--
-- WHAT IT DELIBERATELY DOES NOT DO
--   * It rewrites no row. Nothing is back-filled and nothing is UPDATEd, in
--     particular NOT the idempotency keys of duplicate rows (the engine scout's
--     plan nulled them inside the migration): a data rewrite applied to
--     production on merge, with no review step in front of it, to repair a
--     condition that does not exist. Production held 0 workflow_templates, 0
--     workflow_instances, 0 workflow_schedules and no duplicate key when it was
--     read on 9 October 2026. Where a database DOES hold duplicate live keys the
--     migration REFUSES, naming the count, so a person decides which run keeps
--     its key; it never picks one.
--   * No application code reads or writes any of these columns in the change
--     that adds this file. Code that names them must land AFTER this migration
--     has applied: a select naming a missing column is a 42703 in the deploy
--     window (`select('*')` is safe).
--   * It adds no index on `tasks(workflow_instance_id)` alone. The unique index
--     leads with `firm_id` and the code scopes every read by firm; the only
--     query that would need the bare column is the SET NULL of deleting a run,
--     which nothing in the product does.
--   * It adds no status CHECK on `workflow_instances`: the vocabulary (`waiting`
--     is coming) moves in Python, and the index above is written against the two
--     words that release a key, not against a list of the live ones.
--
-- Additive and idempotent. Locks: ACCESS EXCLUSIVE for the ALTERs and SHARE for
-- the index builds, on three small tables, held to the end of the transaction
-- and taken in the order templates, instances, tasks.
-- ============================================================================

BEGIN;

-- ─── workflow_templates ─────────────────────────────────────────────────────

ALTER TABLE public.workflow_templates
    ADD COLUMN IF NOT EXISTS archived_at timestamptz,
    ADD COLUMN IF NOT EXISTS starter_key text;

DO $$ BEGIN
  IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = 'public.workflow_templates'::regclass
        AND conname  = 'workflow_templates_starter_key_check') THEN
    ALTER TABLE public.workflow_templates
      ADD CONSTRAINT workflow_templates_starter_key_check
      CHECK (starter_key IS NULL
             OR (starter_key = btrim(starter_key)
                 AND char_length(starter_key) BETWEEN 1 AND 100));
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_templates_firm_starter_key
    ON public.workflow_templates (firm_id, starter_key);

COMMENT ON COLUMN public.workflow_templates.archived_at IS
    'When the template was archived, or NULL when it is not (NULL is every template that existed '
    'before migration 481). An archived template is hidden from the list unless asked for, can never '
    'be started and is never fired. Archiving does not delete: a template that has run cannot be '
    'deleted (workflow_instances.template_id has no cascade).';
COMMENT ON COLUMN public.workflow_templates.starter_key IS
    'Which of the CA starter workflows this row is a copy of, or NULL for a template the firm made. '
    'Unique per firm (uq_wf_templates_firm_starter_key), so a starter is installed once per firm; '
    'archiving a starter keeps its key and restoring it is the way back. A duplicate of a starter is '
    'a firm-made template and carries NULL. Validated in Python; the database holds only that it is '
    'not blank, not padded and at most 100 characters. Migration 481.';

-- ─── workflow_instances ─────────────────────────────────────────────────────

-- Refuse, naming the count, rather than let CREATE UNIQUE INDEX fail on the
-- first duplicate with a message about an index. This only counts what the index
-- below would reject; it changes nothing, and which run keeps its key is a
-- person's decision (set the key of the others to NULL, then apply again).
DO $$
DECLARE
  duplicated bigint;
BEGIN
  SELECT count(*) INTO duplicated FROM (
      SELECT 1
      FROM public.workflow_instances
      WHERE idempotency_key IS NOT NULL
        AND status NOT IN ('failed', 'cancelled')
      GROUP BY firm_id, template_id, idempotency_key
      HAVING count(*) > 1
  ) d;
  IF duplicated > 0 THEN
    RAISE EXCEPTION
      'migration 481: % (firm, template, idempotency key) combination(s) already hold more than one '
      'live workflow run, so a unique index cannot be built. Decide which run keeps each key and set '
      'the key of the others to NULL, then apply this migration again. Nothing was changed.', duplicated;
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_wf_instances_live_idempotency
    ON public.workflow_instances (firm_id, template_id, idempotency_key)
    WHERE idempotency_key IS NOT NULL
      AND status NOT IN ('failed', 'cancelled');

COMMENT ON INDEX public.uq_wf_instances_live_idempotency IS
    'One LIVE workflow run per firm, template and idempotency key. A failed or cancelled run does '
    'not hold its key, so an explicit retry (a new run with the same key) is allowed; a completed '
    'run does, so the same event is never processed twice. Partial, so it cannot be named in an '
    'ON CONFLICT: the code that creates a run reads 23505 as "already started". Migration 481.';

-- ─── tasks ──────────────────────────────────────────────────────────────────

ALTER TABLE public.tasks
    ADD COLUMN IF NOT EXISTS workflow_instance_id uuid
        REFERENCES public.workflow_instances(id) ON DELETE SET NULL,
    ADD COLUMN IF NOT EXISTS workflow_step_ref text;

DO $$ BEGIN
  IF NOT EXISTS (
      SELECT 1 FROM pg_constraint
      WHERE conrelid = 'public.tasks'::regclass
        AND conname  = 'tasks_workflow_step_ref_check') THEN
    ALTER TABLE public.tasks
      ADD CONSTRAINT tasks_workflow_step_ref_check
      CHECK (workflow_step_ref IS NULL
             OR (workflow_step_ref = btrim(workflow_step_ref)
                 AND char_length(workflow_step_ref) BETWEEN 1 AND 200));
  END IF;
END $$;

CREATE UNIQUE INDEX IF NOT EXISTS uq_tasks_workflow_step_once
    ON public.tasks (firm_id, workflow_instance_id, workflow_step_ref)
    WHERE workflow_instance_id IS NOT NULL
      AND workflow_step_ref IS NOT NULL;

COMMENT ON COLUMN public.tasks.workflow_instance_id IS
    'The workflow run that created this task, or NULL for a task a person or another door made. '
    'ON DELETE SET NULL: removing a run never removes the work it created. NOT workflow_id, which '
    'references the legacy workflows table. Migration 481.';
COMMENT ON COLUMN public.tasks.workflow_step_ref IS
    'Which step of workflow_instance_id made this task (a step key, or an id from the run''s own '
    'snapshot): text, not a foreign key to workflow_steps, whose rows an edit deletes and re-inserts. '
    'Unique per (firm, run, step) while both are set, soft-deleted tasks included, so a re-run of '
    'the step finds its task instead of making another. Migration 481.';

COMMIT;
