-- 102 — Banking B.4 (Reconciliation Engine)
--
-- EXTENDS the existing bank_reconciliations table (migration 029) into a full
-- reconciliation session and links bank_transactions to a session. Additive and
-- IDEMPOTENT. No duplicate table — we build on the legacy structure.
--
-- The statement date range reuses the existing period_start / period_end columns
-- (the API exposes them as statement_start_date / statement_end_date). Integer
-- paise only; the tie-out is computed in the service from the linked transactions.

-- ── Session lifecycle: open → in_progress → completed (immutable once completed) ─
UPDATE bank_reconciliations SET status = 'completed' WHERE status = 'closed';
ALTER TABLE bank_reconciliations DROP CONSTRAINT IF EXISTS bank_reconciliations_status_check;
ALTER TABLE bank_reconciliations
  ADD CONSTRAINT bank_reconciliations_status_check
  CHECK (status IN ('open', 'in_progress', 'completed'));

-- ── Session attributes required by B.4 ────────────────────────────────────────
ALTER TABLE bank_reconciliations ADD COLUMN IF NOT EXISTS bank_account_id   uuid REFERENCES bank_accounts(id);
ALTER TABLE bank_reconciliations ADD COLUMN IF NOT EXISTS adjustments_paise bigint NOT NULL DEFAULT 0;
ALTER TABLE bank_reconciliations ADD COLUMN IF NOT EXISTS completed_at      timestamptz;
ALTER TABLE bank_reconciliations ADD COLUMN IF NOT EXISTS completed_by      uuid;
ALTER TABLE bank_reconciliations ADD COLUMN IF NOT EXISTS created_by        uuid;
ALTER TABLE bank_reconciliations ADD COLUMN IF NOT EXISTS updated_at        timestamptz DEFAULT now();
CREATE INDEX IF NOT EXISTS idx_bank_recon_account ON bank_reconciliations (bank_account_id);

-- ── Per-transaction reconciliation link (a txn is reconciled iff this is set) ──
ALTER TABLE bank_transactions ADD COLUMN IF NOT EXISTS reconciliation_id uuid REFERENCES bank_reconciliations(id);
CREATE INDEX IF NOT EXISTS idx_bank_txns_reconciliation ON bank_transactions (reconciliation_id);

COMMENT ON COLUMN bank_reconciliations.bank_account_id IS
    'B.4 reconciliation is scoped to a single bank account.';
COMMENT ON COLUMN bank_reconciliations.adjustments_paise IS
    'B.4 documented adjustments (± paise) applied in the balance tie-out.';
COMMENT ON COLUMN bank_reconciliations.status IS
    'B.4 lifecycle: open → in_progress → completed. Completed is immutable.';
COMMENT ON COLUMN bank_transactions.reconciliation_id IS
    'B.4 owning reconciliation session; NULL = unreconciled. Distinct from posted_journal_id.';
