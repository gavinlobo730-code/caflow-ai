-- Migration 681: a firm may have a Partner approve every manual journal (ledger POST-A-456).
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═════════════════════════════════════════════════════════════════
-- Two doors put a manual journal on the books and they asked different people. `POST /api/accounting/journal` with status "posted" asked
-- `accounting` `write` (a Manager and above) and posted at once; `POST /api/accounting/journals/{id}/post`, which posts a SAVED DRAFT, asked
-- `accounting` `approve` (a Partner). So the Approvals queue was a step a Manager could go around by typing the entry again as new, and a
-- firm that wanted every manual journal approved had no way to say so.
--
-- ═════════════════════════════════════════════════════════════════
-- WHAT THIS DOES
-- ═════════════════════════════════════════════════════════════════
-- Adds `firms.manual_journals_need_approval`, NOT NULL, default FALSE, so no firm's work changes when this applies. The API holds every door
-- to one rule (`services/journal_approval_rule.py`): while it is FALSE, anyone who may write the books (`accounting` `write`) may put a manual
-- journal on them, as a new entry or from a saved draft; while it is TRUE, only someone who may approve (`accounting` `approve`) may post one,
-- post a draft, or correct or delete an entry already posted, and everyone else saves a draft for Approvals. A Partner changes it through
-- `PUT /api/accounting/journal-approval` (`settings` `write`). Nothing else reads or writes the column.
--
-- DEPLOY ORDER: the API that reads the column is written to treat a column that does not exist yet as FALSE (the rule a firm has before it
-- can choose), so it is safe on either side of this migration. Idempotent. Reversible: the rollback drops the column.

ALTER TABLE public.firms
  ADD COLUMN IF NOT EXISTS manual_journals_need_approval BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN public.firms.manual_journals_need_approval IS
  'TRUE: only a member who may approve accounting (a Partner, or someone the Team grid gives approve) may post a manual journal, post a '
  'saved draft, or correct or delete a posted one; everyone else saves a draft for Approvals. FALSE: anyone who may write the books may '
  'post either way. Set by a Partner (POST-A-456, migration 681).';
