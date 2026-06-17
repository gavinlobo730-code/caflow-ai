-- PracticeSync AI — Migration 092: chart_of_accounts.system_account_key
-- Cash-basis remediation (Decision B).
--
-- Adds a STABLE key that identifies control accounts (A/R, A/P, Bank, GST,
-- TDS, advances) for the cash-basis reporting engine, so report projection no
-- longer depends on fragile account-name matching. Additive, idempotent,
-- backward-compatible: the resolver falls back to name matching when NULL.
--
-- No financial data is changed. GST/ITR logic is unaffected (CGST Act / IT Act).

ALTER TABLE chart_of_accounts ADD COLUMN IF NOT EXISTS system_account_key TEXT;

COMMENT ON COLUMN chart_of_accounts.system_account_key IS
  'Stable control-account key for reporting (ar|ap|bank|gst_output|gst_input|'
  'tds_payable|tds_receivable|advance_customer|advance_vendor). NULL for ordinary accounts.';

-- Backfill existing charts by name/type. Only fills rows not already keyed so
-- re-running is safe and manual overrides are preserved.
UPDATE chart_of_accounts SET system_account_key = 'ar'
  WHERE system_account_key IS NULL AND account_type = 'Asset'
    AND (account_name ILIKE '%trade receivable%' OR account_name ILIKE '%accounts receivable%'
         OR account_name ILIKE '%sundry debtor%');

UPDATE chart_of_accounts SET system_account_key = 'ap'
  WHERE system_account_key IS NULL AND account_type = 'Liability'
    AND (account_name ILIKE '%trade payable%' OR account_name ILIKE '%accounts payable%'
         OR account_name ILIKE '%sundry creditor%');

UPDATE chart_of_accounts SET system_account_key = 'gst_output'
  WHERE system_account_key IS NULL
    AND (account_name ILIKE '%gst output%' OR account_name ILIKE '%output tax%');

UPDATE chart_of_accounts SET system_account_key = 'gst_input'
  WHERE system_account_key IS NULL
    AND (account_name ILIKE '%gst input%' OR account_name ILIKE '%input tax credit%');

UPDATE chart_of_accounts SET system_account_key = 'tds_payable'
  WHERE system_account_key IS NULL AND account_name ILIKE '%tds payable%';

UPDATE chart_of_accounts SET system_account_key = 'tds_receivable'
  WHERE system_account_key IS NULL AND account_name ILIKE '%tds receivable%';

UPDATE chart_of_accounts SET system_account_key = 'advance_customer'
  WHERE system_account_key IS NULL
    AND (account_name ILIKE '%advance from customer%' OR account_name ILIKE '%customer advance%'
         OR account_name ILIKE '%advance received%');

UPDATE chart_of_accounts SET system_account_key = 'advance_vendor'
  WHERE system_account_key IS NULL
    AND (account_name ILIKE '%advance to vendor%' OR account_name ILIKE '%vendor advance%'
         OR account_name ILIKE '%advance paid%');

-- Bank/Cash last so it cannot mis-claim "Bank Loan" (Liability) or "Bank Charges" (Expense).
UPDATE chart_of_accounts SET system_account_key = 'bank'
  WHERE system_account_key IS NULL AND account_type = 'Asset'
    AND (account_name ILIKE '%bank%' OR account_name ILIKE '%cash%'
         OR account_subtype ILIKE '%bank%' OR account_subtype ILIKE '%cash%');

CREATE INDEX IF NOT EXISTS idx_chart_of_accounts_system_key
  ON chart_of_accounts(firm_id, system_account_key)
  WHERE system_account_key IS NOT NULL;
