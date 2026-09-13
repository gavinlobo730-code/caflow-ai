-- Rollback for migration 377.
--
-- The two columns on `journal_entries` are dropped LAST, after the tables that
-- reference them, and the index with them. Every generated entry survives: it
-- is an ordinary manual journal (source_type = 'manual', deliberately — see
-- the migration header) and loses only the link back to the template that
-- suggested it.
DROP INDEX IF EXISTS public.uq_journal_entries_recurring;
DROP TABLE IF EXISTS public.recurring_journal_runs;
DROP TABLE IF EXISTS public.recurring_journal_template_lines;
ALTER TABLE public.journal_entries DROP COLUMN IF EXISTS recurring_template_id;
ALTER TABLE public.journal_entries DROP COLUMN IF EXISTS recurring_occurrence;
DROP TABLE IF EXISTS public.recurring_journal_templates;
