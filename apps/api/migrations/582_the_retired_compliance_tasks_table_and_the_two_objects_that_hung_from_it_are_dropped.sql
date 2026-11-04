-- Migration 582 — the retired compliance "System B" table, its view and the one foreign key that hung from it are dropped
-- (POST-A-322).
--
-- WHAT WAS WRONG
--   `compliance_records` is the compliance calendar's record. `compliance_tasks` was the older table beside it ("System B"): its three
--   routes, its repository, its seed and the tests only they carried were deleted on 29-10-2026, and production holds no row in it
--   (read on 22-10-2026, 29-10-2026 and 4-11-2026: 0 rows). What was left was the table itself and two objects that depend on it:
--     * the view `compliance_entries` (`SELECT * FROM compliance_tasks`, migration 016; no code reads it: the dashboard's own comment
--       says it used to and now asks the calendar); and
--     * the foreign key `filings.compliance_task_id` -> `compliance_tasks(id)` (`filings_compliance_task_id_fkey`, migration 001).
--       `filings` is the table the period lock reads, so only the CONSTRAINT goes: the column stays, and nothing on production
--       holds a value in it (0 rows with it set, read 4-11-2026).
--   A table nothing reads or writes, with a view and a constraint tying it to a table the period lock reads, is a place for a wrong
--   answer to come from, and it carries four triggers and three policies that a later reader has to learn are dead.
--
-- WHAT THIS DOES (one transaction)
--   1. Refuses to run if `compliance_tasks` holds a single row. A table that was found empty and is not empty now has somebody's
--      records in it, and a migration that drops those is a deletion nobody decided. The table is locked before it is counted, so
--      a row cannot arrive between the count and the drop.
--   2. Drops the view `compliance_entries` if it exists (no CASCADE: it is named, and so is everything else dropped here).
--   3. Drops the constraint `filings_compliance_task_id_fkey` if it exists. The column `filings.compliance_task_id` is left alone.
--   4. Drops the table, with NO CASCADE, so that a dependent object nobody listed (a view, a constraint, a function's column) makes
--      the migration fail and roll back instead of being dropped with it. Its triggers and policies go with it, which is the point.
--   5. Checks the three objects are gone and the `filings` column is still there.
--
-- WHAT IT CHANGES FOR A PERSON: nothing. No screen or route reads the table or the view.
--
-- Written to be safe on a database built from the migrations and on production: the table, the view and the constraint are each
-- dropped only where they exist.

DO $$
DECLARE
  v_rows bigint;
BEGIN
  -- ── 1. a table that holds a row is not dropped ─────────────────────────────────────────────────────────────────────────────
  IF to_regclass('public.compliance_tasks') IS NOT NULL THEN
    -- Locked first, so a row written between the count and the drop cannot be lost with the table. Nothing writes it (migration 170
    -- took the write privilege away and the code that did was deleted), so this costs nothing; it makes the check exact rather than
    -- merely true today.
    LOCK TABLE public.compliance_tasks IN ACCESS EXCLUSIVE MODE;
    EXECUTE 'SELECT count(*) FROM public.compliance_tasks' INTO v_rows;
    IF v_rows > 0 THEN
      RAISE EXCEPTION 'migration 582: public.compliance_tasks holds % row(s); it was empty when this was written. Nothing was dropped. '
                      'Read the rows, decide where they belong, then drop the table by hand.', v_rows;
    END IF;
  END IF;

  -- ── 2. the view over it ────────────────────────────────────────────────────────────────────────────────────────────────────
  IF to_regclass('public.compliance_entries') IS NOT NULL THEN
    DROP VIEW public.compliance_entries;
  END IF;

  -- ── 3. the one foreign key into it (the column stays) ──────────────────────────────────────────────────────────────────────
  IF to_regclass('public.filings') IS NOT NULL THEN
    ALTER TABLE public.filings DROP CONSTRAINT IF EXISTS filings_compliance_task_id_fkey;
  END IF;

  -- ── 4. the table, and nothing it was holding up ────────────────────────────────────────────────────────────────────────────
  IF to_regclass('public.compliance_tasks') IS NOT NULL THEN
    DROP TABLE public.compliance_tasks;
  END IF;

  -- ── 5. check it ────────────────────────────────────────────────────────────────────────────────────────────────────────────
  IF to_regclass('public.compliance_tasks') IS NOT NULL THEN
    RAISE EXCEPTION 'migration 582: public.compliance_tasks is still there';
  END IF;
  IF to_regclass('public.compliance_entries') IS NOT NULL THEN
    RAISE EXCEPTION 'migration 582: public.compliance_entries is still there';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'filings_compliance_task_id_fkey') THEN
    RAISE EXCEPTION 'migration 582: filings_compliance_task_id_fkey is still there';
  END IF;
  IF to_regclass('public.filings') IS NOT NULL AND NOT EXISTS (
       SELECT 1 FROM information_schema.columns
       WHERE table_schema = 'public' AND table_name = 'filings' AND column_name = 'compliance_task_id') THEN
    RAISE EXCEPTION 'migration 582: filings.compliance_task_id was dropped; only its constraint was meant to go';
  END IF;
END $$;
