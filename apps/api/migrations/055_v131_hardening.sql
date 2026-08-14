-- V1.3.1 Database Hardening
-- 1. Journal entry immutability (DB-level trigger)
-- 2. Bank transaction deduplication constraint
-- 3. Performance indexes

-- ─── 1. Journal Immutability Trigger ─────────────────────────────────────────

-- Prevent UPDATE/DELETE on posted journal entries and their lines.
-- Accounting integrity: once is_posted=TRUE, the entry is a permanent ledger record.

CREATE OR REPLACE FUNCTION prevent_posted_journal_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.is_posted = TRUE THEN
        RAISE EXCEPTION 'Cannot modify or delete a posted journal entry (id: %). '
            'Create a reversal entry instead.', OLD.id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION prevent_posted_journal_line_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    v_is_posted BOOLEAN;
BEGIN
    SELECT is_posted INTO v_is_posted
    FROM journal_entries
    WHERE id = OLD.journal_entry_id;

    IF v_is_posted = TRUE THEN
        RAISE EXCEPTION 'Cannot modify or delete lines of a posted journal entry (journal_entry_id: %). '
            'Create a reversal entry instead.', OLD.journal_entry_id
            USING ERRCODE = 'integrity_constraint_violation';
    END IF;
    RETURN NEW;
END;
$$;

-- Trigger on journal_entries: fire BEFORE UPDATE or DELETE
DROP TRIGGER IF EXISTS trg_prevent_posted_journal_update ON journal_entries;
CREATE TRIGGER trg_prevent_posted_journal_update
    BEFORE UPDATE OR DELETE ON journal_entries
    FOR EACH ROW
    EXECUTE FUNCTION prevent_posted_journal_modification();

-- Trigger on journal_lines: fire BEFORE UPDATE or DELETE
DROP TRIGGER IF EXISTS trg_prevent_posted_journal_line_update ON journal_lines;
CREATE TRIGGER trg_prevent_posted_journal_line_update
    BEFORE UPDATE OR DELETE ON journal_lines
    FOR EACH ROW
    EXECUTE FUNCTION prevent_posted_journal_line_modification();


-- ─── 2. Journal Reversal Column ──────────────────────────────────────────────

-- Links a reversal entry back to the original posted entry.
-- NULL = not a reversal; non-NULL = this entry reverses the referenced entry.
ALTER TABLE journal_entries
    ADD COLUMN IF NOT EXISTS reversal_of UUID REFERENCES journal_entries(id);

CREATE INDEX IF NOT EXISTS idx_journal_entries_reversal_of
    ON journal_entries (reversal_of)
    WHERE reversal_of IS NOT NULL;


-- ─── 3. Bank Transaction Deduplication ───────────────────────────────────────

-- Prevent duplicate rows when the same statement is imported twice.
-- Uniqueness on: client + account + date + description + debit + credit
-- balance_paise excluded as it can differ on re-import edge cases.

ALTER TABLE bank_transactions
    ADD COLUMN IF NOT EXISTS import_hash TEXT;

-- Unique constraint via index (partial: only on non-null import_hash)
-- REPLAYABILITY GUARD: this statement names an object that only exists on a
-- database where it was created out-of-band or by a LATER migration, so a
-- clean replay died here. Guarded, not deleted: on a database that has the
-- object (i.e. production) the statement still runs, unchanged.
DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.columns
             WHERE table_schema='public' AND table_name='bank_transactions'
               AND column_name='bank_account_id') THEN
    CREATE UNIQUE INDEX IF NOT EXISTS uq_bank_transactions_import
        ON bank_transactions (client_id, bank_account_id, txn_date, debit_paise, credit_paise, description)
        WHERE bank_account_id IS NOT NULL;
  END IF;
END $$;


-- ─── 4. Performance Indexes ───────────────────────────────────────────────────

-- Timeline events: queried by client_id + created_at for feeds
CREATE INDEX IF NOT EXISTS idx_timeline_client_created
    ON client_timeline_events (client_id, created_at DESC);

-- Payroll runs: common query pattern is (client_id, month)
CREATE INDEX IF NOT EXISTS idx_payroll_runs_client_month
    ON payroll_runs (client_id, month DESC);

-- Journal entries: common query is (client_id, is_posted, entry_date)
CREATE INDEX IF NOT EXISTS idx_journal_entries_client_date
    ON journal_entries (client_id, entry_date DESC)
    WHERE is_posted = TRUE;

-- Bank transactions: reconciliation workspace queries unreconciled by account
CREATE INDEX IF NOT EXISTS idx_bank_txns_unreconciled
    ON bank_transactions (client_id, bank_account_id, txn_date DESC)
    WHERE reconciled = FALSE;


-- ─── 5. Customers/Vendors GRANT Safety Net ───────────────────────────────────

-- Ensure authenticated role has explicit grants on all tables
-- (Belt-and-suspenders in case migration 049 was not applied cleanly)

GRANT SELECT, INSERT, UPDATE, DELETE ON customers TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON vendors   TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON bank_accounts TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON bank_transactions TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON bank_matching_rules TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON salary_structures TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON payroll_employees TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON payroll_runs TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON payroll_slips TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON fixed_assets TO authenticated;
