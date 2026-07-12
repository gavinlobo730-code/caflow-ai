-- Migration 198: corrects one row collaterally mislabelled by migration
-- 197's first (already-applied) pass, whose guard matched only account_code
-- and the old subtype value, not account_name.
--
-- This Supabase project has a second, non-standard-layout firm
-- (a1b2c3d4-0000-0000-0000-000000000001, a test/demo fixture) that reuses
-- account_code '5005' for "Internet & Telephone" instead of "Bank Charges".
-- Its old subtype happened to also be 'Overhead' — the same default every
-- generic-overhead STANDARD_COA account carries — so migration 197's
-- UPDATE for account_code='5005' (guarded only on code + old subtype)
-- collaterally relabelled it to 'Bank Charges' too. Migration 197's file
-- has since been hardened to also require account_name ILIKE the target
-- account, so this cannot recur; this migration repairs the one row it
-- already caused, and is itself idempotent (a no-op if already corrected
-- or if the row's subtype was ever legitimately changed again since).

UPDATE public.chart_of_accounts SET account_subtype = 'Overhead'
WHERE client_id IS NULL AND firm_id = 'a1b2c3d4-0000-0000-0000-000000000001'
  AND account_code = '5005' AND account_name = 'Internet & Telephone'
  AND account_subtype = 'Bank Charges';
