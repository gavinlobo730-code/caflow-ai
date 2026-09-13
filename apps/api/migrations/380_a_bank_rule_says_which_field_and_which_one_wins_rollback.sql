-- Rollback for migration 380.
--
-- Every rule survives and reverts to the behaviour it had: `description_pattern`
-- read against the narration with `contains`, and precedence by created_at. A
-- rule whose CA had set match_field='reference_no' loses that and falls back to
-- matching the narration, which will usually stop it firing rather than make it
-- fire wider — the safe direction for a rule that may be trusted.
DROP INDEX IF EXISTS public.idx_bank_matching_rules_precedence;
ALTER TABLE public.bank_matching_rules
  DROP CONSTRAINT IF EXISTS bank_matching_rules_match_field_check,
  DROP CONSTRAINT IF EXISTS bank_matching_rules_match_operator_check;
ALTER TABLE public.bank_matching_rules
  DROP COLUMN IF EXISTS description_patterns,
  DROP COLUMN IF EXISTS match_operator,
  DROP COLUMN IF EXISTS match_field,
  DROP COLUMN IF EXISTS priority;
