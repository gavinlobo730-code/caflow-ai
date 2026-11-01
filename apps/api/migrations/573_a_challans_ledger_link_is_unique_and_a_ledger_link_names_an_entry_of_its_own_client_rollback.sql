-- Rollback of migration 573: take the two entry checks and the unique index away and put 568's plain index back.
-- Run this BEFORE 568's rollback: a column a trigger's WHEN clause names cannot be dropped.
BEGIN;

DROP TRIGGER IF EXISTS row_journal_entry_journal_entry_id_ins ON public.tds_challans;
DROP TRIGGER IF EXISTS row_journal_entry_journal_entry_id_upd ON public.tds_challans;
DROP TRIGGER IF EXISTS row_journal_entry_journal_entry_id_ins ON public.statutory_remittances;
DROP TRIGGER IF EXISTS row_journal_entry_journal_entry_id_upd ON public.statutory_remittances;
DROP FUNCTION IF EXISTS public.guard_journal_entry(regclass, text);
DROP FUNCTION IF EXISTS public.assert_row_names_a_journal_entry_of_its_client();

DROP INDEX IF EXISTS public.uq_tds_challans_journal_entry;
CREATE INDEX IF NOT EXISTS idx_tds_challans_journal_entry
    ON public.tds_challans (journal_entry_id)
    WHERE journal_entry_id IS NOT NULL;

COMMENT ON COLUMN public.tds_challans.journal_entry_id IS
    'The ledger entry that paid this challan (Dr TDS Payable / Cr Bank). A link only, never a posting; NULL = not tied to an entry. POST-A-272.';

COMMIT;
