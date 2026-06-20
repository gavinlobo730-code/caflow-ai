-- 094 — Banking Phase B.0 Foundation Cleanup
--
-- Purpose: reconcile the schema with the canonical single transaction model that
-- the application code now uses, and add the indexes the foundation needs. This
-- migration is purely ADDITIVE and IDEMPOTENT — it drops no columns and renames
-- nothing, so it is safe to run against the live database.
--
-- Canonical bank_transactions model (verified against the live schema):
--   transaction_date  date    — the transaction date (NOT `txn_date`, which was
--                               only ever referenced by broken indexes/code)
--   match_status      text    — lifecycle: unmatched | matched | posted | ignored
--                               (single source of truth for state)
--   account_id        uuid    — mapped GL (chart_of_accounts) account
--   reconciled_journal_id uuid — the posted journal entry this txn created/links to
--
-- The legacy boolean `reconciled` (migration 029) is retained for backward
-- compatibility and kept in sync by the backend, but `match_status` is canonical.
-- Earlier migrations (055/058) created indexes referencing a non-existent
-- `txn_date` column; those are superseded by the correct indexes below.

-- Performance indexes on the REAL columns (foundation for Phase B.1 queries).
CREATE INDEX IF NOT EXISTS idx_bank_txns_transaction_date
    ON bank_transactions (transaction_date);
CREATE INDEX IF NOT EXISTS idx_bank_txns_match_status
    ON bank_transactions (match_status);
CREATE INDEX IF NOT EXISTS idx_bank_txns_statement
    ON bank_transactions (statement_id);
CREATE INDEX IF NOT EXISTS idx_bank_txns_firm_client
    ON bank_transactions (firm_id, client_id);

-- Backfill: make match_status consistent with the legacy `reconciled` flag for
-- any rows written before the single-model convention. Idempotent (no-op once
-- consistent). A reconciled txn is at least 'matched'; posting sets 'posted'.
UPDATE bank_transactions
   SET match_status = 'matched'
 WHERE reconciled IS TRUE
   AND COALESCE(match_status, 'unmatched') = 'unmatched';

-- Document the canonical model for future maintainers.
COMMENT ON COLUMN bank_transactions.match_status IS
    'Canonical lifecycle: unmatched|matched|posted|ignored. Single source of truth (Phase B.0).';
COMMENT ON COLUMN bank_transactions.transaction_date IS
    'Canonical transaction date. Supersedes the never-created `txn_date` referenced by migrations 055/058.';
COMMENT ON COLUMN bank_transactions.reconciled IS
    'LEGACY (migration 029). Kept in sync for backward compatibility; prefer match_status.';
