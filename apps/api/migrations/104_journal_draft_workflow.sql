-- 104 — Phase 3.5 Draft Journal Workflow (additive, idempotent).
--
-- Adds the origin link (source_type/source_id) so a posted draft can trigger its
-- deferred downstream action (e.g. bank settlement), and posted_by for the audit
-- trail. Reports continue to key off the authoritative is_posted flag. No
-- destructive change. (Posted rows are immutable via prevent_posted_journal_update,
-- so the redundant legacy `status` column is intentionally left untouched here.)

ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS posted_by   uuid;
ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS source_type text;
ALTER TABLE journal_entries ADD COLUMN IF NOT EXISTS source_id   uuid;

CREATE INDEX IF NOT EXISTS idx_je_firm_posted ON journal_entries (firm_id, is_posted);
CREATE INDEX IF NOT EXISTS idx_je_source      ON journal_entries (source_type, source_id);

COMMENT ON COLUMN journal_entries.source_type IS
    'Phase 3.5 origin (bank_transaction | sales_invoice | ...) — drives deferred post-actions.';
COMMENT ON COLUMN journal_entries.posted_by IS
    'Phase 3.5 user who approved/posted the draft (audit trail).';
