-- Migration 051: Phase 2 stabilization schema fixes
-- Fixes identified during stabilization sprint to align schema with router expectations.

-- P0-2: Add paid_paise to client_sales_invoices
-- Tracks cumulative payments received against an invoice.
-- Needed by receipts router to compute invoice status (partially_paid / paid).
ALTER TABLE client_sales_invoices
  ADD COLUMN IF NOT EXISTS paid_paise BIGINT NOT NULL DEFAULT 0;

-- P0-3: Add is_interstate to credit_notes
-- Required by journal service to determine CGST+SGST vs IGST split.
-- CGST Act §8: Intra-state → CGST+SGST; Inter-state → IGST.
ALTER TABLE credit_notes
  ADD COLUMN IF NOT EXISTS is_interstate BOOLEAN NOT NULL DEFAULT FALSE;

-- P0-4: Fix purchase_bill_lines column name mismatch.
-- Migration 050 created the FK column as "purchase_bill_id" but the router
-- inserts using "bill_id". Rename to align with the router expectation.
ALTER TABLE purchase_bill_lines
  RENAME COLUMN purchase_bill_id TO bill_id;

-- Drop the old RLS policy that referenced the old column name
DROP POLICY IF EXISTS "firm_purchase_bill_lines" ON purchase_bill_lines;

-- Recreate RLS policy with the renamed column
CREATE POLICY "firm_purchase_bill_lines" ON purchase_bill_lines
  FOR ALL TO authenticated
  USING (bill_id IN (
    SELECT id FROM purchase_bills WHERE firm_id = get_my_firm_id()
  ));

-- Recreate index on the renamed column for query performance
DROP INDEX IF EXISTS idx_purchase_bill_lines_bill_id;
CREATE INDEX IF NOT EXISTS idx_purchase_bill_lines_bill_id
  ON purchase_bill_lines(bill_id);
