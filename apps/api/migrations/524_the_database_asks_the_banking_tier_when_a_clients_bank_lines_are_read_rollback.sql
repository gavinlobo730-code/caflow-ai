-- Rollback for migration 524: the 6 restrictive select policies it added are dropped.
--
-- Rolling back RE-OPENS the hole 524 closes: a person whose Banking access a Partner has blocked, and a Reviewer
-- assigned to the client, can read the client's bank lines, statements, splits, reconciliations and matching rules
-- over PostgREST with their own sign-in. Nothing else changes; no row is touched.

DROP POLICY IF EXISTS "bank_transactions_banking_read_tier" ON public.bank_transactions;
DROP POLICY IF EXISTS "bank_statements_banking_read_tier" ON public.bank_statements;
DROP POLICY IF EXISTS "bank_transaction_splits_banking_read_tier" ON public.bank_transaction_splits;
DROP POLICY IF EXISTS "bank_reconciliations_banking_read_tier" ON public.bank_reconciliations;
DROP POLICY IF EXISTS "bank_reconciliation_matches_banking_read_tier" ON public.bank_reconciliation_matches;
DROP POLICY IF EXISTS "bank_matching_rules_banking_read_tier" ON public.bank_matching_rules;
