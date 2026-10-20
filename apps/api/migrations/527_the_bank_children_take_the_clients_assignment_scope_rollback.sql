-- Rollback for migration 527: the six policies are dropped, which returns the three bank-child tables to the firm policy
-- (and, since 524, the banking read tier) they carried before. Nothing else changes; no row is touched.

DROP POLICY IF EXISTS "bank_transaction_splits_assignment_scope" ON public.bank_transaction_splits;
DROP POLICY IF EXISTS "bank_transaction_splits_internal_partner_only" ON public.bank_transaction_splits;
DROP POLICY IF EXISTS "bank_transaction_splits_parent_visible" ON public.bank_transaction_splits;
DROP POLICY IF EXISTS "bank_matching_rules_assignment_scope" ON public.bank_matching_rules;
DROP POLICY IF EXISTS "bank_matching_rules_internal_partner_only" ON public.bank_matching_rules;
DROP POLICY IF EXISTS "bank_reconciliation_matches_parent_visible" ON public.bank_reconciliation_matches;
