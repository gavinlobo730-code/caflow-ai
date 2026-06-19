-- PracticeSync AI — Migration 098: chart_of_accounts GST split + revenue key
-- Adds system_account_key values for revenue and per-head GST accounts.
-- Additive, idempotent (WHERE system_account_key IS NULL guards re-runs).
-- No financial data changed. CGST Act §8 / §9 logic unaffected.

-- Update column comment to document new keys.
COMMENT ON COLUMN chart_of_accounts.system_account_key IS
  'Stable control-account key for reporting and posting (ar|ap|bank|revenue|'
  'gst_output|gst_cgst|gst_sgst|gst_igst|gst_input|'
  'tds_payable|tds_receivable|advance_customer|advance_vendor). NULL for ordinary accounts.';

-- Revenue: standard CoA "Sales Revenue"
UPDATE chart_of_accounts SET system_account_key = 'revenue'
  WHERE system_account_key IS NULL
    AND account_type IN ('Income', 'Revenue')
    AND account_name ILIKE '%Sales Revenue%';

-- Revenue: CA-practice CoA "Professional Fees" variants (covers "Other Professional Fees")
UPDATE chart_of_accounts SET system_account_key = 'revenue'
  WHERE system_account_key IS NULL
    AND account_type IN ('Income', 'Revenue')
    AND (account_name ILIKE '%Professional Fees%' OR account_name ILIKE '%Professional Fee%');

-- CGST output payable (Liability only — prevents mis-claiming GST Input assets)
-- CGST Act §9: CGST on intra-state outward supplies.
UPDATE chart_of_accounts SET system_account_key = 'gst_cgst'
  WHERE system_account_key IS NULL
    AND account_type = 'Liability'
    AND account_name ILIKE '%CGST%';

-- SGST output payable (Liability only)
-- CGST Act §9: SGST on intra-state outward supplies.
UPDATE chart_of_accounts SET system_account_key = 'gst_sgst'
  WHERE system_account_key IS NULL
    AND account_type = 'Liability'
    AND account_name ILIKE '%SGST%';

-- IGST output payable (Liability only)
-- CGST Act §9 / IGST Act §5: IGST on inter-state outward supplies.
UPDATE chart_of_accounts SET system_account_key = 'gst_igst'
  WHERE system_account_key IS NULL
    AND account_type = 'Liability'
    AND (account_name ILIKE '%IGST%' OR account_name ILIKE '%Integrated GST%');

-- Extend index to cover new keys (index definition is conditional on NOT NULL).
-- The existing idx_chart_of_accounts_system_key from migration 092 already covers all values.
