-- Rollback of migration 520: drops both CHECK constraints. After this the database no longer refuses a journal attachment list that
-- is not an array (or has more than twenty elements) or a chart-of-accounts mapping the classifier cannot read; the API models still
-- do. For fidelity with the previous schema, not for use.
ALTER TABLE IF EXISTS public.chart_of_accounts DROP CONSTRAINT IF EXISTS chart_of_accounts_schedule_iii_mapping_check;
ALTER TABLE IF EXISTS public.journal_entries DROP CONSTRAINT IF EXISTS journal_entries_attachments_check;
