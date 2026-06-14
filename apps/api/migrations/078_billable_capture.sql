-- PracticeSync AI — Migration 078: Billable / billed capture (Batch 5)
-- Amendment v1.1 (Phase 10B) — DATA-CAPTURE ONLY (no analytics).
--
-- Reuses Batch-1 columns (time_entries.is_billable, time_entries.billable_rate_paise,
-- users.cost_rate_paise). Adds the system-controlled billed linkage so future
-- billing workflows can rely on it without reconciliation:
--   * billed_invoice_id is the AUTHORITATIVE linkage.
--   * is_billed is a GENERATED column derived from billed_invoice_id — it cannot
--     be set manually (Postgres rejects writes to GENERATED ALWAYS columns), so it
--     is system-controlled by construction and always consistent.
-- Additive, backward-compatible, idempotent.

ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS billed_invoice_id uuid;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='client_sales_invoices')
     AND NOT EXISTS (
       SELECT 1 FROM information_schema.table_constraints
       WHERE constraint_name='time_entries_billed_invoice_id_fkey' AND table_name='time_entries'
     ) THEN
    ALTER TABLE time_entries
      ADD CONSTRAINT time_entries_billed_invoice_id_fkey
      FOREIGN KEY (billed_invoice_id) REFERENCES client_sales_invoices(id) ON DELETE SET NULL;
  END IF;
END $$;

-- System-controlled, derived, non-editable.
ALTER TABLE time_entries
  ADD COLUMN IF NOT EXISTS is_billed boolean
  GENERATED ALWAYS AS (billed_invoice_id IS NOT NULL) STORED;

-- Unbilled-work query: billable AND not yet billed.
CREATE INDEX IF NOT EXISTS idx_time_entries_unbilled
  ON time_entries(firm_id, client_id)
  WHERE is_billable AND billed_invoice_id IS NULL;

COMMENT ON COLUMN time_entries.billed_invoice_id IS
  'Batch 5: authoritative billed linkage (the sales invoice that billed this time). Set by the system; future time-based billing relies on this without reconciliation.';
COMMENT ON COLUMN time_entries.is_billed IS
  'Batch 5: GENERATED from billed_invoice_id (system-controlled; cannot be edited manually).';
