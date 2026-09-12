-- Rollback for migration 370. Drops only the policies 370 creates; the
-- firm-wide PERMISSIVE policy on each table is untouched, so a rollback
-- returns the table to firm-scoped-only — which is what it was before.
DROP POLICY IF EXISTS bank_accounts_assignment_scope ON public.bank_accounts;
DROP POLICY IF EXISTS debit_notes_assignment_scope ON public.debit_notes;
DROP POLICY IF EXISTS purchase_credit_notes_assignment_scope ON public.purchase_credit_notes;
DROP POLICY IF EXISTS sales_debit_notes_assignment_scope ON public.sales_debit_notes;
DROP POLICY IF EXISTS gstr2b_reconciliations_assignment_scope ON public.gstr2b_reconciliations;
DROP POLICY IF EXISTS tds_lower_deduction_certificates_assignment_scope ON public.tds_lower_deduction_certificates;
