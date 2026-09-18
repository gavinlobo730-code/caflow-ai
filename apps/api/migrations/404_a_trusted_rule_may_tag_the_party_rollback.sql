-- Rollback for 404. Drops only what 404 added; migration 257's columns on
-- bank_transactions.payee_* are untouched.
BEGIN;
ALTER TABLE public.bank_transactions
  DROP CONSTRAINT IF EXISTS bank_transactions_draft_payee_type_check;
ALTER TABLE public.bank_transactions
  DROP COLUMN IF EXISTS draft_payee_type,
  DROP COLUMN IF EXISTS draft_payee_id;
ALTER TABLE public.bank_matching_rules
  DROP CONSTRAINT IF EXISTS bank_matching_rules_payee_pair_check,
  DROP CONSTRAINT IF EXISTS bank_matching_rules_payee_type_check;
ALTER TABLE public.bank_matching_rules
  DROP COLUMN IF EXISTS payee_type,
  DROP COLUMN IF EXISTS payee_id;
COMMIT;
