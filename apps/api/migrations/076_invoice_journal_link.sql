-- PracticeSync AI — Migration 076: Invoice→Journal link (Batch 3.1 hardening)
-- Amendment v1.1 (Phase 10B).
--
-- Persists the posted journal on the sales invoice so an "issued-but-unposted"
-- invoice is deterministically detectable (status='issued' AND journal_entry_id
-- IS NULL) and remediable. Backward-compatible, additive, idempotent.

ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS journal_entry_id uuid;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='journal_entries')
     AND NOT EXISTS (
       SELECT 1 FROM information_schema.table_constraints
       WHERE constraint_name = 'client_sales_invoices_journal_entry_id_fkey'
         AND table_name = 'client_sales_invoices'
     ) THEN
    ALTER TABLE client_sales_invoices
      ADD CONSTRAINT client_sales_invoices_journal_entry_id_fkey
      FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id) ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_unposted
  ON client_sales_invoices(firm_id) WHERE status = 'issued' AND journal_entry_id IS NULL;

COMMENT ON COLUMN client_sales_invoices.journal_entry_id IS
  'Batch 3.1: the posted journal entry for this issued invoice. NULL on a draft, or on a (legacy) issued-but-unposted invoice pending remediation.';
