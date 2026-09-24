-- Migration 413: a trusted rule FLAGS a TDS decision — BANK-11 step 3, the
-- half migration 404 refused, answered as D19 on 24-09-2026.
--
-- ── WHAT 404 SAID, AND WHY THIS IS NOT A REVERSAL ───────────────────────────
-- Migration 404's own header: "TDS STAYS OUT AND THAT IS THE WHOLE SAFETY
-- ARGUMENT — a withholding decides a statutory liability under s.201 and
-- belongs in front of a human however trusted the rule. No column here, and
-- the guard asserts RuleSuggestion has no TDS field."
--
-- THAT ARGUMENT IS UNTOUCHED. A trusted rule still cannot decide a
-- withholding: no section, no rate, no base, no amount. What it gains is the
-- ability to say "a human must look at this one", which is the opposite kind
-- of thing — it can only ADD work for a person, never remove it, and it moves
-- no figure in any journal.
--
-- ── WHY THE FLAG IS WORTH A MIGRATION ───────────────────────────────────────
-- Rent (s.194I), professional fees (s.194J) and contractor payments (s.194C)
-- are exactly the recurring lines a trusted rule exists for. A rule that posts
-- the payment and says nothing about TDS sends the CA back through every one
-- of them anyway, which removes most of the reason to trust the rule at all.
-- So the choice was never "decide it or ignore it": it was "decide it, ignore
-- it, or route it", and routing is the only one of the three that is both
-- useful and safe.
--
-- The asymmetry is what settles it. An under-deduction disallows the WHOLE
-- expenditure under s.40(a)(ia), puts the tax on the client under s.201(1)
-- with s.201(1A) interest, and is INVISIBLE — the entry posts, the books
-- balance, the P&L reads correctly, and it surfaces in an assessment order two
-- years later. A rule that picks the wrong ACCOUNT shows up on a statement
-- somebody reads every month. A flagged line is visible; a wrong deduction is
-- not.
--
-- ── TWO COLUMNS, NOT ONE, AND THAT IS MIGRATION 382's SHAPE ─────────────────
-- `bank_matching_rules.flags_tds_decision` is what the CA marks on the RULE.
-- `bank_transactions.draft_flags_tds_decision` is the PROPOSAL a firing rule
-- wrote onto the line, and it is cleared like every other draft_* column when
-- the line is re-drafted or the proposal rejected.
-- `bank_transactions.tds_decision_needed` is the RECORDED fact, stamped when
-- the line was actually passed.
--
-- That is exactly migration 382's split between `draft_gst_rate_bps` (the
-- machine's proposal, which a caller may override) and `gst_rate_bps` (what
-- was POSTED). Collapsing them would make a rejected proposal indistinguishable
-- from a recorded one, and the recorded one is the whole point: it says an
-- unattended rule posted this line and nobody has looked at the withholding.
--
-- ── RESOLVED IS ITS OWN COLUMN, NOT A CLEARED BOOLEAN ───────────────────────
-- `tds_decision_resolved_at` / `_by` rather than setting `tds_decision_needed`
-- back to false. Three states, not two: never flagged, flagged and waiting,
-- flagged and dealt with. Clearing the boolean loses the third, and the third
-- is the audit answer to "did anyone look at the withholding on this line" —
-- which is the question s.201 proceedings ask. A row that was never flagged
-- and a row somebody cleared must not read the same.
--
-- ── NOTHING IS BACK-FILLED AND EVERY DEFAULT IS THE OLD BEHAVIOUR ───────────
-- `false` on both booleans, NULL on both resolution columns. Every rule that
-- exists today flags nothing, every line already passed is unflagged, and no
-- CA's queue changes on the day this deploys. A back-fill would assert that
-- somebody had decided something about lines nobody has looked at.

ALTER TABLE public.bank_matching_rules
  ADD COLUMN IF NOT EXISTS flags_tds_decision BOOLEAN NOT NULL DEFAULT false;

COMMENT ON COLUMN public.bank_matching_rules.flags_tds_decision IS
  'The CA marks this rule as covering payments that may attract TDS. A rule '
  'NEVER decides the withholding — no section, no rate, no amount (see '
  'migration 404). It only routes the line it passed to a human worklist. '
  'Default false: every existing rule flags nothing.';

ALTER TABLE public.bank_transactions
  ADD COLUMN IF NOT EXISTS draft_flags_tds_decision BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS tds_decision_needed      BOOLEAN NOT NULL DEFAULT false,
  ADD COLUMN IF NOT EXISTS tds_decision_resolved_at TIMESTAMPTZ,
  ADD COLUMN IF NOT EXISTS tds_decision_resolved_by UUID REFERENCES public.users(id);

COMMENT ON COLUMN public.bank_transactions.draft_flags_tds_decision IS
  'The PROPOSAL: a firing rule said this line may attract TDS. Cleared with '
  'every other draft_* column when the line is re-drafted. Not the recorded '
  'fact — that is tds_decision_needed, migration 382''s split.';

COMMENT ON COLUMN public.bank_transactions.tds_decision_needed IS
  'RECORDED: this line was passed by a rule marked flags_tds_decision, so a '
  'human still has to decide the withholding. Never cleared — resolution is '
  'tds_decision_resolved_at, because "never flagged" and "flagged and dealt '
  'with" are different answers to the question s.201 proceedings ask.';

COMMENT ON COLUMN public.bank_transactions.tds_decision_resolved_at IS
  'When a human settled the withholding question on this line. NULL while it '
  'is outstanding. Pending = tds_decision_needed AND this IS NULL.';

COMMENT ON COLUMN public.bank_transactions.tds_decision_resolved_by IS
  'public.users.id — the INTERNAL user id, not the Supabase auth id, matching '
  'created_by/posted_by everywhere else in this schema.';

-- The worklist's own index. PARTIAL, on exactly the pending predicate, because
-- the overwhelming majority of rows are never flagged and an index over all of
-- them would be mostly dead pages.
--
-- The date column is `transaction_date`. Checked against the production
-- snapshot rather than taken from a neighbouring migration: migration 055
-- indexes this table on `txn_date` AND on `bank_account_id`, and production
-- has NEITHER — bank_transactions reaches its account through `statement_id`,
-- which CLAUDE.md states and `tests/fixtures/production_schema_2026-09-03.json`
-- confirms. A migration is applied to the live database on merge with no
-- review step in front of it, so a column name copied from a neighbour is one
-- deploy failure that blocks every later migration behind it.
CREATE INDEX IF NOT EXISTS idx_bank_txn_tds_decision_pending
  ON public.bank_transactions (firm_id, client_id, transaction_date)
  WHERE tds_decision_needed AND tds_decision_resolved_at IS NULL;
