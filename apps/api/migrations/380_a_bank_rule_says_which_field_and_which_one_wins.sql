-- Migration 380: a bank rule says WHICH FIELD it reads, HOW it compares, how
-- many alternatives it accepts, and WHICH RULE WINS. BANK-11, steps 1 and 2.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT WAS WRONG
-- ═══════════════════════════════════════════════════════════════════════════
-- `domain/banking/rules.rule_matches` was one case-insensitive substring of the
-- narration, an amount range and a direction. That is the whole engine, and it
-- fails a practice in two ways every month:
--
--   PRECEDENCE WAS CREATION ORDER, with no way to change it. Three fetch sites
--   ordered by `created_at` and `match_rule` takes the FIRST firing rule, so a
--   broad rule written in April permanently shadowed the narrow one written in
--   July. The only fix available to a CA was to delete and re-create the broad
--   rule, which loses its trusted flag and its history.
--
--   ONE PATTERN, ONE FIELD. "NEFT from any of these three customers" was three
--   rules. A reference number the bank puts in `reference_no` — a UTR, a cheque
--   number, a standing-instruction id, which is often the ONLY stable part of a
--   narration the bank rewrites every month — could not be matched at all,
--   though the column has existed on `bank_transactions` throughout. Nor could
--   the `payee_name` the normaliser extracts.
--
-- ═══════════════════════════════════════════════════════════════════════════
-- WHAT THIS ADDS, AND WHAT IT DELIBERATELY DOES NOT
-- ═══════════════════════════════════════════════════════════════════════════
-- `priority`, `match_field`, `match_operator` and `description_patterns`.
-- Every one has a default that reproduces today's behaviour exactly, so every
-- existing rule keeps firing on precisely the transactions it fires on now and
-- in precisely the order it fires in now — the backfill is the DEFAULT, and
-- there is no UPDATE.
--
-- WHAT A RULE MAY PROPOSE IS UNCHANGED, and that is the safety line. A TRUSTED
-- rule passes its lines with no click (migration 322) — the one place this
-- product acts unprompted — so widening the PAYLOAD widens what posts
-- unattended. Split legs, a party, and a TDS treatment are BANK-11's step 3 and
-- are not here: they need that decision taken deliberately, not as a side
-- effect of better matching. Matching wider is a different thing: a CA types
-- every pattern themselves, and the widest case has always been available
-- anyway (an empty `description_pattern` matches every transaction).
--
-- Additive. Idempotent. Reversible: 380_..._rollback.sql.

ALTER TABLE public.bank_matching_rules
  -- LOWER FIRST. 100 rather than 0 so a CA can put a rule above the existing
  -- ones without renumbering them, which is the move they will actually want:
  -- the shadowing rule is usually the old one.
  ADD COLUMN IF NOT EXISTS priority integer NOT NULL DEFAULT 100,

  -- Which column of `bank_transactions` the pattern is read against. 'any'
  -- means the three text fields together, which is what a CA means by "this
  -- appears somewhere on the line".
  ADD COLUMN IF NOT EXISTS match_field text NOT NULL DEFAULT 'description',

  -- How. `contains` is what the engine has always done and stays the default;
  -- `starts_with` and `equals` are strictly NARROWER, which matters because
  -- the whole point of the priority column above is that broad rules were
  -- shadowing narrow ones.
  ADD COLUMN IF NOT EXISTS match_operator text NOT NULL DEFAULT 'contains',

  -- FURTHER alternatives, matched with OR against the same field and operator.
  -- An array rather than a child table: this is a list of strings a CA types
  -- into one box, with no per-item attributes to hold, and a child table would
  -- make the rules fetch a join. NULL and {} both mean "just
  -- description_pattern", so nothing existing changes.
  ADD COLUMN IF NOT EXISTS description_patterns text[];

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.bank_matching_rules'::regclass
                   AND conname = 'bank_matching_rules_match_field_check') THEN
    ALTER TABLE public.bank_matching_rules
      ADD CONSTRAINT bank_matching_rules_match_field_check
      CHECK (match_field IN ('description', 'reference_no', 'payee_name', 'any'));
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint
                 WHERE conrelid = 'public.bank_matching_rules'::regclass
                   AND conname = 'bank_matching_rules_match_operator_check') THEN
    ALTER TABLE public.bank_matching_rules
      ADD CONSTRAINT bank_matching_rules_match_operator_check
      CHECK (match_operator IN ('contains', 'starts_with', 'equals'));
  END IF;
END $$;

COMMENT ON COLUMN public.bank_matching_rules.priority IS
    'Evaluation order, LOWER FIRST, with created_at as the tiebreak so the '
    'existing order is exactly preserved at the default of 100. match_rule '
    'takes the first firing rule, so this is what stops a broad rule written '
    'early from permanently shadowing a narrow one written later. Migration '
    '380 (BANK-11).';
COMMENT ON COLUMN public.bank_matching_rules.match_field IS
    'Which text of the transaction the pattern is read against: description '
    '(the default, and what the engine always did), reference_no, payee_name, '
    'or any of the three. reference_no is often the only stable part of a line '
    'whose narration the bank rewrites monthly. Migration 380.';
COMMENT ON COLUMN public.bank_matching_rules.match_operator IS
    'contains (the default and the historic behaviour), starts_with, or '
    'equals. The latter two are strictly narrower. Migration 380.';
COMMENT ON COLUMN public.bank_matching_rules.description_patterns IS
    'Further alternatives ORed with description_pattern, against the same '
    'field and operator — "any of these three customers" is one rule, not '
    'three. NULL or {} means just description_pattern. Migration 380.';

-- The queue and the redraft sweep fetch active rules per client and evaluate
-- them in order; the index matches that read exactly.
CREATE INDEX IF NOT EXISTS idx_bank_matching_rules_precedence
    ON public.bank_matching_rules (firm_id, client_id, priority, created_at)
 WHERE is_active;
