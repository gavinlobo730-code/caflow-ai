-- Rollback for migration 369: restore migration 322's bank_transaction_entry_state(),
-- with the human-coded predicate back inline in the CASE, and drop the column.
--
-- WHAT THIS RESTORES IS THE HOLE. Without `coded_by_a_human` as a column,
-- `pass_ready(only_trusted=True)` cannot exclude a human-coded line in the
-- QUERY, so the nightly trusted-rule sweep picks up any READY line still
-- carrying a trusted rule's draft_rule_id — including one the CA answered
-- themselves — and posts it credited to the person who trusted the rule.
-- The ledger content is the CA's; the authority named on it is not.
--
-- Drop the column LAST: the trigger below no longer assigns it, and a column
-- declared NOT NULL DEFAULT false would otherwise sit frozen at whatever the
-- last write left, which is worse than not having it.
--
-- Run this only to unblock something 369 broke, and only long enough to find
-- out what. Idempotent, and safe to re-run.

BEGIN;

-- Migration 322's body, verbatim.
CREATE OR REPLACE FUNCTION public.bank_transaction_entry_state()
RETURNS TRIGGER LANGUAGE plpgsql
SET search_path = pg_catalog, public AS $$
BEGIN
  -- An answer from a human clears the machine's complaint. Compared on
  -- UPDATE only; an INSERT has no OLD.
  IF TG_OP = 'UPDATE' AND NEW.draft_error IS NOT NULL AND (
       NEW.account_id        IS DISTINCT FROM OLD.account_id
    OR NEW.matched_entity_id IS DISTINCT FROM OLD.matched_entity_id
    OR NEW.category          IS DISTINCT FROM OLD.category
    OR NEW.transfer_pair_id  IS DISTINCT FROM OLD.transfer_pair_id
    OR NEW.has_splits        IS DISTINCT FROM OLD.has_splits
    OR NEW.match_status      IS DISTINCT FROM OLD.match_status
  ) THEN
    NEW.draft_error := NULL;
  END IF;

  NEW.entry_state :=
    CASE
      WHEN NEW.match_status = 'posted'  THEN 'passed'
      WHEN NEW.match_status = 'ignored' THEN 'set_aside'
      WHEN NEW.transfer_pair_id IS NOT NULL AND NEW.transfer_is_primary = false THEN 'covered'
      WHEN NEW.account_id IS NOT NULL
        OR NEW.matched_entity_id IS NOT NULL
        OR NEW.has_splits
        OR (NEW.transfer_pair_id IS NOT NULL AND NEW.transfer_is_primary = true)
        OR NEW.category IN ('Customer Payment', 'Vendor Payment', 'GST Payment')
        THEN 'ready'
      WHEN NEW.draft_error IS NOT NULL   THEN 'needs_you'
      WHEN NEW.draft_grade = 'ready'     THEN 'ready'
      WHEN NEW.draft_grade = 'proposed'  THEN 'proposed'
      ELSE 'needs_you'
    END;
  RETURN NEW;
END;
$$;

ALTER TABLE public.bank_transactions DROP COLUMN IF EXISTS coded_by_a_human;

COMMIT;
