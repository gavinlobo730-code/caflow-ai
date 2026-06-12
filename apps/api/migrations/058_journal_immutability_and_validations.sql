-- Migration 058: Journal immutability trigger + validation constraints
-- Prevents modification of posted journals and adds financial integrity guards.

-- ── Journal immutability trigger ─────────────────────────────────────────────
-- Once a journal entry is posted (is_posted = true), its lines must not change.
-- CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT

CREATE OR REPLACE FUNCTION prevent_posted_journal_update()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.is_posted = TRUE THEN
        RAISE EXCEPTION 'Cannot modify a posted journal entry (id: %). Create a reversal instead.', OLD.id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_journal_immutability ON journal_entries;
CREATE TRIGGER trg_journal_immutability
    BEFORE UPDATE ON journal_entries
    FOR EACH ROW
    EXECUTE FUNCTION prevent_posted_journal_update();

-- Prevent deleting posted journals
CREATE OR REPLACE FUNCTION prevent_posted_journal_delete()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    IF OLD.is_posted = TRUE THEN
        RAISE EXCEPTION 'Cannot delete a posted journal entry (id: %). Create a reversal instead.', OLD.id;
    END IF;
    RETURN OLD;
END;
$$;

DROP TRIGGER IF EXISTS trg_journal_immutability_delete ON journal_entries;
CREATE TRIGGER trg_journal_immutability_delete
    BEFORE DELETE ON journal_entries
    FOR EACH ROW
    EXECUTE FUNCTION prevent_posted_journal_delete();

-- ── Prevent posting to archived accounts ─────────────────────────────────────
CREATE OR REPLACE FUNCTION prevent_archived_account_journal_line()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
DECLARE
    acc_active BOOLEAN;
BEGIN
    SELECT is_active INTO acc_active
    FROM chart_of_accounts
    WHERE id = NEW.account_id;

    IF acc_active IS FALSE THEN
        RAISE EXCEPTION 'Cannot post to archived account (id: %). Reactivate or choose another account.', NEW.account_id;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_archived_account_check ON journal_lines;
CREATE TRIGGER trg_archived_account_check
    BEFORE INSERT ON journal_lines
    FOR EACH ROW
    EXECUTE FUNCTION prevent_archived_account_journal_line();

-- ── Index for performance ─────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_journal_entries_firm_client_posted
    ON journal_entries(firm_id, client_id, is_posted);

CREATE INDEX IF NOT EXISTS idx_bank_transactions_firm_client_reconciled
    ON bank_transactions(firm_id, client_id, reconciled);
