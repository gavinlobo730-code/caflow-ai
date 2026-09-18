-- Migration 404: a rule may propose WHO the money went to — BANK-11 step 3.
--
-- ── WHAT THE OWNER DECIDED, AND WHAT OF IT WAS ALREADY BUILT ────────────────
-- The recorded decision (docs/audits/questions-for-the-owner.md) is option (a):
-- "A trusted rule can post '₹11,800 = ₹10,000 rent + ₹1,800 GST' in one go, and
-- can tag the party. TDS stays out."
--
-- The worked example in that sentence was ALREADY BUILT and had been for
-- months: `bank_rules.gst_rate_bps` + `is_interstate` (migration 254) travel
-- through `draft_gst_rate_bps` into `bank_posting_service.build_inclusive_lines`,
-- which splits an inclusive amount into its taxable value and its GST heads.
-- A trusted rule posts exactly that split today, unattended. So the half of
-- step 3 that needed building is the OTHER half — the party — and this
-- migration is only that.
--
-- ── WHY THE PARTY IS SAFE TO PROPOSE AND A SPLIT LEG IS A SEPARATE QUESTION ──
-- `payee_type`/`payee_id` (migration 257) LABEL a transaction. They are not a
-- journal leg: nothing in `posting_map.build_lines`, the settlement or the
-- reversal reads them, `domain/banking/entry.coded_by_a_human` does not count
-- them, and the settlement target is `matched_entity_type`/`matched_entity_id`,
-- which is a different pair checked against the real table on every use. So a
-- rule that tags the party changes what a screen can group and filter by and
-- changes no figure — which is what makes it safe to apply with nobody
-- watching.
--
-- A general SPLIT LEG is not, and the decision does not in fact settle its
-- shape. A rule cannot know a future transaction's amount, so fixed amounts
-- per account would fire only on lines that happen to total the same, and
-- PERCENTAGES are the only form that generalises — 60% factory / 40% office on
-- a bill that differs every month. Percentages are a real feature and a
-- different one from the example the decision gives; they are deliberately NOT
-- built here, and `RuleSuggestion` gaining a `splits` field stays what the
-- guard in tests/test_a_bank_rule_says_which_field_and_which_one_wins.py
-- refuses.
--
-- ── TDS STAYS OUT AND THAT IS THE WHOLE SAFETY ARGUMENT ─────────────────────
-- A withholding decides a statutory liability under s.201 and belongs in front
-- of a human however trusted the rule. No column here, and the guard asserts
-- `RuleSuggestion` has no TDS field.
--
-- ── THE TABLE IS `bank_matching_rules` ──────────────────────────────────────
-- Not `bank_rules`, which does not exist. `domain/banking/rules.py` and the
-- prose everywhere call it "a bank rule", and the first draft of this
-- migration targeted that name — it would have failed on the production
-- deploy, which is the one place a migration is applied with no review step in
-- front of it. Migration 380 is the one to copy from.
--
-- ── SHAPE ───────────────────────────────────────────────────────────────────
-- Both columns nullable with NO default, so every existing rule proposes no
-- party and nothing a firm already wrote changes behaviour on the day this
-- lands. The CHECK is migration 257's own three values, restated here rather
-- than referenced because a CHECK cannot point at another table's constraint —
-- and a test reads BOTH files so a value added to one and not the other fails
-- in CI rather than at INSERT time on production.
--
-- `payee_id` carries no foreign key for exactly migration 257's reason: the
-- reference is polymorphic. It is validated against the real table at APPLY
-- time by `bank_payee_service`, the same door a human goes through.

BEGIN;

ALTER TABLE public.bank_matching_rules
  ADD COLUMN IF NOT EXISTS payee_type TEXT,
  ADD COLUMN IF NOT EXISTS payee_id   UUID;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.bank_matching_rules'::regclass
       AND conname  = 'bank_matching_rules_payee_type_check'
  ) THEN
    ALTER TABLE public.bank_matching_rules
      ADD CONSTRAINT bank_matching_rules_payee_type_check
      CHECK (payee_type IS NULL OR payee_type IN ('customer', 'vendor', 'other'));
  END IF;
END $$;

-- A pointer with no kind cannot be resolved, and a kind of 'other' names no
-- table to point INTO — the same pairing bank_payee_service enforces on the
-- human door, so a rule cannot record what a person could not type.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.bank_matching_rules'::regclass
       AND conname  = 'bank_matching_rules_payee_pair_check'
  ) THEN
    ALTER TABLE public.bank_matching_rules
      ADD CONSTRAINT bank_matching_rules_payee_pair_check
      CHECK (payee_id IS NULL OR payee_type IN ('customer', 'vendor'));
  END IF;
END $$;

COMMENT ON COLUMN public.bank_matching_rules.payee_type IS
  'BANK-11 step 3. Which party table payee_id points into, or ''other'' for a '
  'party this product does not hold. LABELS the transaction; never a journal '
  'leg. Applied through bank_payee_service, the same door a human uses.';
COMMENT ON COLUMN public.bank_matching_rules.payee_id IS
  'BANK-11 step 3. Polymorphic, no FK — migration 257 records why. Validated '
  'at apply time, not here.';

-- The transaction carries the PROPOSAL the same way it carries every other
-- one, so the ordinary Pass applies it and the screen can show it before
-- anybody clicks. A proposal is not the value: draft_* is what a rule
-- suggested, payee_* is what is recorded.
ALTER TABLE public.bank_transactions
  ADD COLUMN IF NOT EXISTS draft_payee_type TEXT,
  ADD COLUMN IF NOT EXISTS draft_payee_id   UUID;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conrelid = 'public.bank_transactions'::regclass
       AND conname  = 'bank_transactions_draft_payee_type_check'
  ) THEN
    ALTER TABLE public.bank_transactions
      ADD CONSTRAINT bank_transactions_draft_payee_type_check
      CHECK (draft_payee_type IS NULL OR draft_payee_type IN ('customer', 'vendor', 'other'));
  END IF;
END $$;

COMMENT ON COLUMN public.bank_transactions.draft_payee_type IS
  'BANK-11 step 3 — what a rule PROPOSED. payee_type is what was recorded.';

COMMIT;
