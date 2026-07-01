-- Migration 147: Multi-Currency — Phase 2 (Accounting Foundation). ADDITIVE ONLY.
--
-- Makes the general ledger currency-aware per the frozen architecture
-- (docs/architecture/06-multi-currency-phase0.md). The base (INR) amount stays
-- authoritative in journal_lines.debit_paise / credit_paise — reports read those
-- unchanged. Every new column defaults to the INR / rate=1 state, so INR postings
-- are byte-for-byte identical and the feature stays dormant until all gates open.
--
-- NOT here (later phases): foreign documents, FX gain/loss/rounding accounts,
-- realized/unrealized FX, revaluation, conversion, reporting. No existing column
-- is removed or altered; no posting behaviour changes.

-- ── journal_lines: per-line currency metadata + foreign (txn) amounts (G4) ─────
-- Static columns take a constant DEFAULT, so ADD COLUMN backfills existing rows
-- to the INR identity WITHOUT firing the posted-line immutability trigger
-- (migration 055) — ADD COLUMN ... DEFAULT is metadata-only DDL, not row DML.
-- The foreign-amount / rate-provenance columns are left NULL for historical rows
-- (they are INR: foreign == base) and are populated going forward by the kernel;
-- they are NOT backfilled because updating a posted line is (correctly) blocked.
ALTER TABLE public.journal_lines
  ADD COLUMN IF NOT EXISTS txn_currency  CHAR(3)      NOT NULL DEFAULT 'INR',
  ADD COLUMN IF NOT EXISTS base_currency CHAR(3)      NOT NULL DEFAULT 'INR',
  ADD COLUMN IF NOT EXISTS exchange_rate NUMERIC(18,8) NOT NULL DEFAULT 1
                                          CHECK (exchange_rate > 0),
  ADD COLUMN IF NOT EXISTS txn_debit     BIGINT,
  ADD COLUMN IF NOT EXISTS txn_credit    BIGINT,
  ADD COLUMN IF NOT EXISTS rate_source   TEXT,
  ADD COLUMN IF NOT EXISTS rate_type     TEXT NOT NULL DEFAULT 'booking'
                                          CHECK (rate_type IN ('booking','gst_notified','customs','closing')),
  ADD COLUMN IF NOT EXISTS rate_date     DATE;

-- ── journal_entries: rate-selection provenance (G6) ───────────────────────────
-- Defaults keep INR (auto-resolved) entries inert: no rate was "selected".
ALTER TABLE public.journal_entries
  ADD COLUMN IF NOT EXISTS rate_selected_by UUID,
  ADD COLUMN IF NOT EXISTS rate_overridden  BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS rate_selected_at TIMESTAMPTZ;

-- Immutability of the new columns is INHERITED, not newly created — and is exactly
-- as strong as the protection on the existing base amounts (debit_paise/credit_paise):
--   • journal_entries — trg_journal_immutability (BEFORE UPDATE) + _delete freeze a
--     posted entry, so rate_selected_by / rate_overridden / rate_selected_at can never
--     change once posted.
--   • journal_lines   — frozen by the append-only posting kernel (writes each line
--     once, never updates it; corrections go through reverse + re-post) together with
--     the posted-entry lock. This is the SAME guarantee the base amounts already rely
--     on. (Note: the live DB carries no line-level UPDATE trigger — pre-existing drift
--     from migration 055; addressing that is a separate hardening, out of this phase's
--     "additive, no posting-behaviour change" scope.)
-- This phase adds NO trigger and changes NO posting behaviour.
