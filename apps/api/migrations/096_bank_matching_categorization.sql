-- 096 — Banking B.2 (Matching & Categorization)
--
-- Additive and IDEMPOTENT. Adds categorization + manual-match linkage to
-- bank_transactions and a suggested_category to the rule engine. No data mutation.

-- ── Categorization (B.2.2) — controlled vocabulary, never free-form ──────────
ALTER TABLE bank_transactions ADD COLUMN IF NOT EXISTS category text;
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bank_txns_category_check') THEN
    ALTER TABLE bank_transactions ADD CONSTRAINT bank_txns_category_check CHECK (
      category IS NULL OR category IN (
        'Sales Receipt','Customer Payment','Vendor Payment','Expense','GST Payment',
        'Salary','Loan','Capital','Transfer','Interest','Other'
      )
    );
  END IF;
END $$;

-- ── Manual match linkage (B.2.5) — link to the matched business entity ───────
ALTER TABLE bank_transactions ADD COLUMN IF NOT EXISTS matched_entity_type text;
ALTER TABLE bank_transactions ADD COLUMN IF NOT EXISTS matched_entity_id   uuid;
ALTER TABLE bank_transactions ADD COLUMN IF NOT EXISTS matched_by          uuid;
ALTER TABLE bank_transactions ADD COLUMN IF NOT EXISTS matched_at          timestamptz;
ALTER TABLE bank_transactions ADD COLUMN IF NOT EXISTS needs_review        boolean DEFAULT false;

DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'bank_txns_matched_entity_type_check') THEN
    ALTER TABLE bank_transactions ADD CONSTRAINT bank_txns_matched_entity_type_check CHECK (
      matched_entity_type IS NULL OR matched_entity_type IN (
        'sales_invoice','purchase_bill','receipt','purchase_payment','journal_entry','manual'
      )
    );
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_bank_txns_category ON bank_transactions (client_id, category);
CREATE INDEX IF NOT EXISTS idx_bank_txns_matched_entity ON bank_transactions (matched_entity_type, matched_entity_id);

-- ── Rule engine: rules suggest a CATEGORY (B.2.3) ────────────────────────────
ALTER TABLE bank_matching_rules ADD COLUMN IF NOT EXISTS suggested_category text;

COMMENT ON COLUMN bank_transactions.category IS
    'B.2 controlled category (suggestion-confirmed). NULL = uncategorized.';
COMMENT ON COLUMN bank_transactions.matched_entity_type IS
    'B.2 manual/accepted match target. Linkage only — NOT a journal posting (that is B.3).';
