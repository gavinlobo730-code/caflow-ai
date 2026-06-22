-- Migration 112: Add NOT VALID CHECK constraints for Indian regulatory field formats
-- NOT VALID skips the table scan on existing rows; only new/updated rows are checked.
-- Run VALIDATE CONSTRAINT in a maintenance window to check existing rows.

-- ── firms ──────────────────────────────────────────────────────────────────
ALTER TABLE firms
  ADD CONSTRAINT firms_pan_format
    CHECK (pan IS NULL OR pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$') NOT VALID,
  ADD CONSTRAINT firms_gstin_format
    CHECK (gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$') NOT VALID,
  ADD CONSTRAINT firms_pincode_format
    CHECK (pincode IS NULL OR pincode ~ '^[1-9][0-9]{5}$') NOT VALID;

-- ── customers ──────────────────────────────────────────────────────────────
ALTER TABLE customers
  ADD CONSTRAINT customers_pan_format
    CHECK (pan IS NULL OR pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$') NOT VALID,
  ADD CONSTRAINT customers_gstin_format
    CHECK (gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$') NOT VALID;

-- ── vendors ────────────────────────────────────────────────────────────────
ALTER TABLE vendors
  ADD CONSTRAINT vendors_pan_format
    CHECK (pan IS NULL OR pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$') NOT VALID,
  ADD CONSTRAINT vendors_gstin_format
    CHECK (gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$') NOT VALID;

-- ── payroll_employees ──────────────────────────────────────────────────────
ALTER TABLE payroll_employees
  ADD CONSTRAINT payroll_employees_pan_format
    CHECK (pan IS NULL OR pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$') NOT VALID;

-- ── tds_certificates ───────────────────────────────────────────────────────
-- IT Act §203: PANNOTAVBL and PANAPPLIED are valid substitutes per TRACES.
ALTER TABLE tds_certificates
  ADD CONSTRAINT tds_certificates_pan_format
    CHECK (
      deductee_pan IS NULL
      OR deductee_pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'
      OR deductee_pan IN ('PANNOTAVBL', 'PANAPPLIED')
    ) NOT VALID;

-- ── tds_challans ───────────────────────────────────────────────────────────
-- BSR code: 7 numeric digits per Income Tax Dept challan format.
ALTER TABLE tds_challans
  ADD CONSTRAINT tds_challans_bsr_code_format
    CHECK (bsr_code IS NULL OR bsr_code ~ '^[0-9]{7}$') NOT VALID;

-- ── gstr1_returns ──────────────────────────────────────────────────────────
ALTER TABLE gstr1_returns
  ADD CONSTRAINT gstr1_returns_gstin_format
    CHECK (gstin IS NULL OR gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$') NOT VALID;

-- ── fee_invoices ───────────────────────────────────────────────────────────
-- GST Rule 46: invoice number max 16 alphanumeric chars.
ALTER TABLE fee_invoices
  ADD CONSTRAINT fee_invoices_invoice_no_length
    CHECK (invoice_no IS NULL OR LENGTH(invoice_no) <= 16) NOT VALID;

-- Rollback: run 112_check_constraints_rollback.sql
