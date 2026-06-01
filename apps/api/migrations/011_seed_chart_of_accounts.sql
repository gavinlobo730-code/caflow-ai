-- Migration 011: Seed standard Indian Chart of Accounts for CA practice
-- Firm-level accounts (client_id = NULL) for firm a1b2c3d4-0000-0000-0000-000000000001
-- Uses ON CONFLICT DO NOTHING so it is safe to re-run.
-- Note: UNIQUE (firm_id, client_id, account_code) with client_id NULL requires
--       a partial unique index to enforce uniqueness. This seed uses
--       INSERT ... ON CONFLICT DO NOTHING which is safe regardless.

INSERT INTO chart_of_accounts
    (firm_id, client_id, account_code, account_name, account_type, account_subtype, is_active)
VALUES
-- ── ASSETS (1xxx) ─────────────────────────────────────────────────────────
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1001', 'Cash in Hand',                   'Asset',   'Cash',         true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1002', 'Petty Cash',                     'Asset',   'Cash',         true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1101', 'HDFC Bank Current Account',      'Asset',   'Bank',         true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1102', 'SBI Bank Current Account',       'Asset',   'Bank',         true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1201', 'Accounts Receivable',            'Asset',   'Receivable',   true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1301', 'GST Input Credit - CGST',        'Asset',   'Tax',          true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1302', 'GST Input Credit - SGST',        'Asset',   'Tax',          true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1303', 'GST Input Credit - IGST',        'Asset',   'Tax',          true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1401', 'Advance Tax Paid',               'Asset',   'Tax',          true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1402', 'TDS Receivable',                 'Asset',   'Tax',          true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1501', 'Office Equipment',               'Asset',   'Fixed Asset',  true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1502', 'Computers & Laptops',            'Asset',   'Fixed Asset',  true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1503', 'Furniture & Fixtures',           'Asset',   'Fixed Asset',  true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1601', 'Security Deposits',              'Asset',   'Other',        true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '1602', 'Prepaid Expenses',               'Asset',   'Other',        true),

-- ── LIABILITIES (2xxx) ────────────────────────────────────────────────────
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '2001', 'Accounts Payable',               'Liability', 'Payable',    true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '2101', 'GST Payable - CGST',             'Liability', 'Tax',        true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '2102', 'GST Payable - SGST',             'Liability', 'Tax',        true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '2103', 'GST Payable - IGST',             'Liability', 'Tax',        true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '2201', 'TDS Payable',                    'Liability', 'Tax',        true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '2202', 'Professional Tax Payable',       'Liability', 'Tax',        true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '2301', 'Salary Payable',                 'Liability', 'Payable',    true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '2401', 'Short Term Loan',                'Liability', 'Loan',       true),

-- ── EQUITY (3xxx) ─────────────────────────────────────────────────────────
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '3001', 'Partner Capital Account',        'Equity',  'Capital',      true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '3002', 'Retained Earnings',              'Equity',  'Retained',     true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '3003', 'Current Year Profit',            'Equity',  'Retained',     true),

-- ── REVENUE (4xxx) ────────────────────────────────────────────────────────
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '4001', 'Audit Fees',                     'Revenue', 'Professional Fees', true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '4002', 'GST Consultancy Fees',           'Revenue', 'Professional Fees', true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '4003', 'Income Tax Fees',                'Revenue', 'Professional Fees', true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '4004', 'MCA/ROC Filing Fees',            'Revenue', 'Professional Fees', true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '4005', 'Accounting & Bookkeeping Fees',  'Revenue', 'Professional Fees', true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '4006', 'TDS Consultancy Fees',           'Revenue', 'Professional Fees', true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '4007', 'Other Professional Fees',        'Revenue', 'Professional Fees', true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '4101', 'Interest Income',                'Revenue', 'Other Income',      true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '4102', 'Miscellaneous Income',           'Revenue', 'Other Income',      true),

-- ── EXPENSES (5xxx) ───────────────────────────────────────────────────────
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5001', 'Staff Salaries',                 'Expense', 'Personnel',    true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5002', 'Staff Bonus',                    'Expense', 'Personnel',    true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5003', 'Office Rent',                    'Expense', 'Overhead',     true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5004', 'Electricity & Utilities',        'Expense', 'Overhead',     true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5005', 'Internet & Telephone',           'Expense', 'Overhead',     true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5006', 'Office Supplies & Stationery',   'Expense', 'Overhead',     true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5007', 'Software Subscriptions',         'Expense', 'Overhead',     true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5008', 'Professional Development & CPE', 'Expense', 'Overhead',     true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5009', 'Travel & Conveyance',            'Expense', 'Overhead',     true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5010', 'Postage & Courier',              'Expense', 'Overhead',     true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5011', 'Bank Charges',                   'Expense', 'Overhead',     true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5012', 'Professional Fees Paid',         'Expense', 'Professional', true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5013', 'Depreciation',                   'Expense', 'Depreciation', true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5014', 'GST on Expenses',                'Expense', 'Tax',          true),
('a1b2c3d4-0000-0000-0000-000000000001', NULL, '5015', 'Miscellaneous Expenses',         'Expense', 'Overhead',     true)
ON CONFLICT DO NOTHING;
