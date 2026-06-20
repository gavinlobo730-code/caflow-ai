-- 095 — Banking B.1 (Bank Feed Foundation): dedup + file metadata
--
-- Additive and IDEMPOTENT — adds columns/indexes only, no data mutation. Safe on
-- the live database (bank tables are empty at time of writing).

-- Per-transaction dedup fingerprint (domain.banking.dedup.transaction_hash).
ALTER TABLE bank_transactions ADD COLUMN IF NOT EXISTS import_hash text;
CREATE INDEX IF NOT EXISTS idx_bank_txns_import_hash
    ON bank_transactions (client_id, import_hash);

-- Statement file metadata + upload provenance (Part A: upload history / audit).
ALTER TABLE bank_statements ADD COLUMN IF NOT EXISTS file_name      text;
ALTER TABLE bank_statements ADD COLUMN IF NOT EXISTS file_size_bytes bigint;
ALTER TABLE bank_statements ADD COLUMN IF NOT EXISTS source_format  text;   -- 'csv' | 'xlsx'
ALTER TABLE bank_statements ADD COLUMN IF NOT EXISTS file_hash      text;   -- duplicate-file detection
ALTER TABLE bank_statements ADD COLUMN IF NOT EXISTS imported_count integer;
ALTER TABLE bank_statements ADD COLUMN IF NOT EXISTS duplicate_count integer;

CREATE INDEX IF NOT EXISTS idx_bank_statements_file_hash
    ON bank_statements (firm_id, file_hash);

COMMENT ON COLUMN bank_transactions.import_hash IS
    'Deterministic dedup fingerprint (B.1). Re-importing the same row is a no-op.';
COMMENT ON COLUMN bank_statements.source_format IS
    'Upload format: csv | xlsx. Normalization happens server-side (B.1).';
