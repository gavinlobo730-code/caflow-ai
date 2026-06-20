-- 097 — Banking B.3 (Posting Engine)
--
-- Additive and IDEMPOTENT. Adds the posting link (duplicate-protection) to
-- bank_transactions and a paid_paise balance to purchase_bills (settlement).
-- No data mutation.

-- ── Posting link / duplicate protection (B.3.5) ──────────────────────────────
ALTER TABLE bank_transactions ADD COLUMN IF NOT EXISTS posted_journal_id uuid;
ALTER TABLE bank_transactions ADD COLUMN IF NOT EXISTS posted_at         timestamptz;
ALTER TABLE bank_transactions ADD COLUMN IF NOT EXISTS posted_by         uuid;
CREATE INDEX IF NOT EXISTS idx_bank_txns_posted_journal
    ON bank_transactions (posted_journal_id);

-- ── Purchase bill settlement balance (B.3.4) ─────────────────────────────────
-- Sales invoices already carry paid_paise; bills did not. Default 0; settlement
-- caps at total (never over-allocate).
ALTER TABLE purchase_bills ADD COLUMN IF NOT EXISTS paid_paise bigint NOT NULL DEFAULT 0;

COMMENT ON COLUMN bank_transactions.posted_journal_id IS
    'B.3 posted journal entry (idempotency: one journal per transaction).';
COMMENT ON COLUMN purchase_bills.paid_paise IS
    'B.3 settled amount (paise). status flips to partially_paid / paid accordingly.';
