-- Rollback of migration 568: forget which ledger entry each TDS challan was tied to. The challans and the journal entries stay as they
-- were; only the link goes, so every challan reads "not tied to an entry" again.

BEGIN;

DROP INDEX IF EXISTS public.idx_tds_challans_journal_entry;
ALTER TABLE public.tds_challans DROP COLUMN IF EXISTS journal_entry_id;

COMMIT;
