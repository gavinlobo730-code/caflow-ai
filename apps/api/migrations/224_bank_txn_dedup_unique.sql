-- Migration 224: enforce bank-transaction dedup at the DB level.
--
-- The importer already dedups on (client_id, import_hash) in application code
-- (services/banking_service.py::_existing_hashes), but two concurrent re-imports
-- of the same statement could each pass that check before the other commits and
-- both insert — a duplicate the app layer can't prevent. This UNIQUE index makes
-- re-importing idempotent at the DB level too; the import insert uses
-- upsert(ignore_duplicates=True) on this key, so a racing duplicate is silently
-- ignored rather than erroring.
--
-- import_hash already embeds client_id, but the composite key mirrors the
-- importer's dedup query and keeps the guarantee explicit and tenant-safe.
-- Rows with a NULL import_hash (e.g. manually-entered transactions) are exempt —
-- Postgres treats NULLs as distinct — so multiple such lines per client are fine.
-- Replaces the redundant NON-unique idx_bank_txns_import_hash on the same columns.
DROP INDEX IF EXISTS idx_bank_txns_import_hash;
CREATE UNIQUE INDEX IF NOT EXISTS uq_bank_txns_client_import_hash
    ON bank_transactions (client_id, import_hash);
