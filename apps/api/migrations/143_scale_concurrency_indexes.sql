-- Migration 143: Scale & Concurrency (Production Readiness Phase 3) — indexes.
--
-- H2 — DB-backed journal idempotency. The kernel de-dups on
--      (client_id, reference_no, entry_date) with a SELECT-then-INSERT (TOCTOU) and
--      NO database backstop, so concurrent posts / retries could create duplicate
--      journals. This partial UNIQUE index makes the invariant atomic; the kernel now
--      catches 23505 and returns the existing entry (idempotent). Verified: production
--      currently has 0 duplicate (firm,client,reference_no,entry_date) groups.
CREATE UNIQUE INDEX IF NOT EXISTS uq_journal_entries_firm_client_ref_date
  ON public.journal_entries (firm_id, client_id, reference_no, entry_date)
  WHERE deleted_at IS NULL AND reference_no IS NOT NULL;

-- M22 — source-document journal_entry_id foreign keys were unindexed, forcing a scan
-- on every ledger/reconciliation join. journal_lines(journal_entry_id) is already
-- indexed; add the missing source-doc ones.
CREATE INDEX IF NOT EXISTS idx_csi_journal_entry_id  ON public.client_sales_invoices (journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_pb_journal_entry_id   ON public.purchase_bills (journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_rcpt_journal_entry_id ON public.receipts (journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_pp_journal_entry_id   ON public.purchase_payments (journal_entry_id);
