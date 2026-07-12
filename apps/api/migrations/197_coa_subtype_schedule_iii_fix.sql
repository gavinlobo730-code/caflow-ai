-- Migration 197: fix Chart-of-Accounts subtypes that don't match the
-- Schedule III bucket-matching keywords in
-- apps/web/app/clients/[id]/accounting/page.tsx's bsBucket()/plBucket() —
-- a substring scan of account_subtype, not a lookup table — so several
-- STANDARD_COA accounts were landing in a generic "Other Current Assets" /
-- "Other Current Liabilities" / "Other Expenses" bucket on the Balance
-- Sheet / P&L instead of their own dedicated Schedule III line, even though
-- every rupee had posted to the correct ACCOUNT all along.
--
-- Found while explaining a CA's Balance Sheet: Inventory (subtype "Current
-- Asset") and Cost of Goods Sold (subtype "Direct Expense") were both
-- falling into the generic bucket instead of "Inventories" / "Cost of
-- Materials Consumed". Auditing every STANDARD_COA row against the same
-- bucket logic found the identical pattern on Purchases, Trade Payables,
-- Short Term Loan, Long Term Loan, Salaries Expense, Staff Welfare,
-- Depreciation Expense and Bank Charges.
--
-- Depreciation Expense's fix additionally corrects
-- domain/reporting/builders.py's AS-3 Cash Flow Statement, whose non-cash
-- depreciation add-back does an EXACT match on
-- subtype.strip().lower() == 'depreciation' — that match has never fired
-- for any firm with the old "Non-cash Expense" subtype either.
--
-- Only the PRESENTATION LABEL changes here; no money moves. Idempotent and
-- non-destructive: each UPDATE is guarded on account_code, the OLD default
-- subtype value, AND account_name (ILIKE) — account_code alone is NOT
-- reliably the same account across every firm in this project (a non-
-- standard-layout firm reuses '5005' for "Internet & Telephone" instead of
-- "Bank Charges"; see migration 198, which corrects the one row that a
-- code-only guard in this migration's first, less careful run collaterally
-- relabelled). A firm that has already customised one of these subtypes
-- away from the seed default is left untouched either way.

UPDATE public.chart_of_accounts SET account_subtype = 'Inventory'
WHERE client_id IS NULL AND account_code = '1202' AND account_subtype = 'Current Asset'
  AND account_name ILIKE '%Inventor%';

UPDATE public.chart_of_accounts SET account_subtype = 'Cost of Goods Sold'
WHERE client_id IS NULL AND account_code = '5000' AND account_subtype = 'Direct Expense'
  AND account_name ILIKE '%Cost of Goods Sold%';

UPDATE public.chart_of_accounts SET account_subtype = 'Purchases'
WHERE client_id IS NULL AND account_code = '5001' AND account_subtype = 'Direct Expense'
  AND account_name ILIKE '%Purchase%';

UPDATE public.chart_of_accounts SET account_subtype = 'Payable'
WHERE client_id IS NULL AND account_code = '2001' AND account_subtype = 'Current Liability'
  AND account_name ILIKE '%Payable%';

UPDATE public.chart_of_accounts SET account_subtype = 'Short Term Loan'
WHERE client_id IS NULL AND account_code = '2101' AND account_subtype = 'Loan'
  AND account_name ILIKE '%Short Term Loan%';

UPDATE public.chart_of_accounts SET account_subtype = 'Long Term Loan'
WHERE client_id IS NULL AND account_code = '2201' AND account_subtype = 'Loan'
  AND account_name ILIKE '%Long Term Loan%';

UPDATE public.chart_of_accounts SET account_subtype = 'Salary'
WHERE client_id IS NULL AND account_code = '5002' AND account_subtype = 'Personnel'
  AND account_name ILIKE '%Salar%';

UPDATE public.chart_of_accounts SET account_subtype = 'Staff Welfare'
WHERE client_id IS NULL AND account_code = '5013' AND account_subtype = 'Personnel'
  AND account_name ILIKE '%Staff Welfare%';

UPDATE public.chart_of_accounts SET account_subtype = 'Depreciation'
WHERE client_id IS NULL AND account_code = '5003' AND account_subtype = 'Non-cash Expense'
  AND account_name ILIKE '%Depreciation%';

UPDATE public.chart_of_accounts SET account_subtype = 'Bank Charges'
WHERE client_id IS NULL AND account_code = '5005' AND account_subtype = 'Overhead'
  AND account_name ILIKE '%Bank Charges%';
