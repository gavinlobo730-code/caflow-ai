-- 369 — The nightly trusted-rule sweep must not pass a line the CA coded
-- themselves, and `coded_by_a_human` becomes a column so it can say so.
--
-- WHAT WAS WRONG (BANK-16)
--     A trusted rule passes its lines with no click — an owner decision of
--     2026-09-03, and the one place the product acts unprompted. The design
--     (docs/architecture/09-bank-entries.md) grounds that in ONE sentence:
--     "Its lines post on the authority of the person who trusted it ...
--     There is no system user, because there is no such person to answer
--     for it."
--
--     `pass_ready(only_trusted=True)` selected every READY line carrying a
--     trusted rule's `draft_rule_id`. But a line the CA has since coded
--     THEMSELVES still carries that draft_rule_id — drafting stamps the row,
--     and answering it does not clear the stamp. So the sweep picked it up.
--
--     `pass_entry` then did the right thing with the CONTENT and the wrong
--     thing with the AUTHORITY: `if not E.coded_by_a_human(txn)` means the
--     draft is not applied over the human's answer, so what posts is what the
--     CA chose — but `actor = rule["trusted_by"]`, so `journal_entries.
--     created_by`, `bank_transactions.posted_by` and the audit row all name
--     the person who trusted the RULE, with `source = bank_trusted_rule`.
--     The register then says "Passed by rule Bank charges, trusted by Priya"
--     over a posting whose ledger, entity and GST treatment came from someone
--     else. That is exactly the attribution the design says must not exist.
--
--     And it posts unprompted at all. Coding a line is not deciding to post
--     it; the CA may have answered the account and left the queue meaning to
--     look again. The rule's authority covers the rule's proposal, and a line
--     a human answered is not the rule's proposal.
--
-- WHY A COLUMN RATHER THAN A FILTER IN PYTHON
--     The sweep is chunked: fifty rows ordered by date, then `remaining` from
--     a COUNT over the same filter, and `jobs/bank_trusted_rules_job.py` loops
--     until `remaining` is 0 or a chunk does nothing. Dropping the human-coded
--     rows AFTER the fetch breaks both halves — the chunk under-fills, and a
--     chunk whose first fifty rows are all human-coded returns zero, ends the
--     loop, and leaves every passable line behind it unswept until tomorrow.
--     A silent cap, and the sweep would read as working.
--
--     So the exclusion has to be IN the query, where it applies to the rows
--     and the count alike. Restating the predicate as five chained PostgREST
--     filters would be a THIRD spelling of a rule that already exists in two
--     (the trigger below and domain/banking/entry.py), which is the drift
--     CLAUDE.md's parity rule exists to stop.
--
--     `bank_transactions` already carries two trigger-maintained columns for
--     precisely this reason — `entry_state` (322) and `has_splits` (322) —
--     so this is that pattern, not a new one.
--
-- THE PREDICATE IS MOVED, NOT COPIED
--     `bank_transaction_entry_state()` already computed it, inline, as the
--     'ready' branch of its CASE. It now assigns NEW.coded_by_a_human FIRST
--     and the CASE READS that column. One expression, used twice, so the
--     column and the state cannot disagree about what "the CA answered this"
--     means. The Python twin domain/banking/entry.py::coded_by_a_human has
--     existed since 322 and is unchanged; test_bank_entry_state_parity_pg.py
--     now asserts the column against it for every case in STATE_TABLE.
--
-- WHAT IS DELIBERATELY NOT CHANGED
--     `pass_entry` still posts a human-coded line when a PERSON asks — from
--     the detail, or from "Pass N ready", where the actor is that person and
--     the attribution is true. Only the unprompted sweep steps back.
--
-- Idempotent, and safe to re-run.

BEGIN;

ALTER TABLE public.bank_transactions
  ADD COLUMN IF NOT EXISTS coded_by_a_human BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.bank_transactions.coded_by_a_human IS
  'The CA answered this line themselves — the ready branch that owes nothing '
  'to a draft. Maintained by bank_transaction_entry_state(); application code '
  'never writes it. Python twin: domain/banking/entry.py::coded_by_a_human.';

-- A NULL category makes `NEW.category IN (...)` NULL, and a boolean column
-- declared NOT NULL will not take it. The assignment is COALESCEd rather than
-- each term, so the OR chain still reads as the rule. entry_state is unchanged
-- by that: a CASE falls through on NULL exactly as it does on false.
CREATE OR REPLACE FUNCTION public.bank_transaction_entry_state()
RETURNS TRIGGER LANGUAGE plpgsql
SET search_path = pg_catalog, public AS $$
BEGIN
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

  NEW.coded_by_a_human := COALESCE(
       NEW.account_id IS NOT NULL
    OR NEW.matched_entity_id IS NOT NULL
    OR NEW.has_splits
    OR (NEW.transfer_pair_id IS NOT NULL AND NEW.transfer_is_primary = true)
    OR NEW.category IN ('Customer Payment', 'Vendor Payment', 'GST Payment'),
    false);

  NEW.entry_state :=
    CASE
      WHEN NEW.match_status = 'posted'  THEN 'passed'
      WHEN NEW.match_status = 'ignored' THEN 'set_aside'
      WHEN NEW.transfer_pair_id IS NOT NULL AND NEW.transfer_is_primary = false THEN 'covered'
      WHEN NEW.coded_by_a_human          THEN 'ready'
      WHEN NEW.draft_error IS NOT NULL   THEN 'needs_you'
      WHEN NEW.draft_grade = 'ready'     THEN 'ready'
      WHEN NEW.draft_grade = 'proposed'  THEN 'proposed'
      ELSE 'needs_you'
    END;
  RETURN NEW;
END;
$$;

-- Backfill through the trigger itself — 322's own idiom. The BEFORE trigger
-- overwrites both computed columns from the row, so a no-op UPDATE of
-- entry_state sets coded_by_a_human on every row that predates the column.
UPDATE public.bank_transactions SET entry_state = entry_state;

-- The sweep's filter is an index on (firm_id, client_id, entry_state,
-- coded_by_a_human, draft_rule_id) in spirit; the existing entry_state index
-- carries the selective part and the two booleans are cheap to re-check, so
-- no new index is added. Recorded so nobody adds one reflexively.

COMMIT;
