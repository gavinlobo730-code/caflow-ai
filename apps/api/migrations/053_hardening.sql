-- Migration 053: Harden RLS to enforce client_id isolation alongside firm_id
-- Replaces permissive firm-only policies with combined firm+client policies
-- so users can only access rows belonging to clients in their own firm.

-- ============================================================
-- client_sales_invoices
-- ============================================================
DROP POLICY IF EXISTS "firm_client_sales_invoices" ON client_sales_invoices;
CREATE POLICY "firm_client_isolation" ON client_sales_invoices
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- client_sales_invoice_lines  (no firm_id — joins through parent)
-- ============================================================
DROP POLICY IF EXISTS "firm_client_sales_invoice_lines" ON client_sales_invoice_lines;
CREATE POLICY "firm_client_isolation" ON client_sales_invoice_lines
    FOR ALL TO authenticated
    USING (
        sales_invoice_id IN (
            SELECT csi.id FROM client_sales_invoices csi
            WHERE csi.firm_id = get_my_firm_id()
            AND csi.client_id IN (
                SELECT id FROM clients WHERE firm_id = get_my_firm_id()
            )
        )
    );

-- ============================================================
-- receipts
-- ============================================================
DROP POLICY IF EXISTS "firm_receipts" ON receipts;
CREATE POLICY "firm_client_isolation" ON receipts
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- receipt_allocations  (no firm_id — joins through receipts)
-- ============================================================
DROP POLICY IF EXISTS "firm_receipt_allocations" ON receipt_allocations;
CREATE POLICY "firm_client_isolation" ON receipt_allocations
    FOR ALL TO authenticated
    USING (
        receipt_id IN (
            SELECT r.id FROM receipts r
            WHERE r.firm_id = get_my_firm_id()
            AND r.client_id IN (
                SELECT id FROM clients WHERE firm_id = get_my_firm_id()
            )
        )
    );

-- ============================================================
-- credit_notes
-- ============================================================
DROP POLICY IF EXISTS "firm_credit_notes" ON credit_notes;
CREATE POLICY "firm_client_isolation" ON credit_notes
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- credit_note_lines  (no firm_id — joins through credit_notes)
-- ============================================================
DROP POLICY IF EXISTS "firm_credit_note_lines" ON credit_note_lines;
CREATE POLICY "firm_client_isolation" ON credit_note_lines
    FOR ALL TO authenticated
    USING (
        credit_note_id IN (
            SELECT cn.id FROM credit_notes cn
            WHERE cn.firm_id = get_my_firm_id()
            AND cn.client_id IN (
                SELECT id FROM clients WHERE firm_id = get_my_firm_id()
            )
        )
    );

-- ============================================================
-- purchase_bills
-- ============================================================
DROP POLICY IF EXISTS "firm_purchase_bills" ON purchase_bills;
CREATE POLICY "firm_client_isolation" ON purchase_bills
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- purchase_bill_lines  (no firm_id — joins through purchase_bills)
-- ============================================================
DROP POLICY IF EXISTS "firm_purchase_bill_lines" ON purchase_bill_lines;
CREATE POLICY "firm_client_isolation" ON purchase_bill_lines
    FOR ALL TO authenticated
    USING (
        purchase_bill_id IN (
            SELECT pb.id FROM purchase_bills pb
            WHERE pb.firm_id = get_my_firm_id()
            AND pb.client_id IN (
                SELECT id FROM clients WHERE firm_id = get_my_firm_id()
            )
        )
    );

-- ============================================================
-- purchase_payments
-- ============================================================
DROP POLICY IF EXISTS "firm_purchase_payments" ON purchase_payments;
CREATE POLICY "firm_client_isolation" ON purchase_payments
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- journal_entries  (check existing policy name from earlier migrations)
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON journal_entries;
DROP POLICY IF EXISTS "firm_journal_entries" ON journal_entries;
CREATE POLICY "firm_client_isolation" ON journal_entries
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- journal_lines  (no firm_id — joins through journal_entries)
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON journal_lines;
DROP POLICY IF EXISTS "firm_journal_lines" ON journal_lines;
CREATE POLICY "firm_client_isolation" ON journal_lines
    FOR ALL TO authenticated
    USING (
        journal_entry_id IN (
            SELECT je.id FROM journal_entries je
            WHERE je.firm_id = get_my_firm_id()
            AND je.client_id IN (
                SELECT id FROM clients WHERE firm_id = get_my_firm_id()
            )
        )
    );

-- ============================================================
-- gstr1_returns
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON gstr1_returns;
DROP POLICY IF EXISTS "firm_gstr1_returns" ON gstr1_returns;
CREATE POLICY "firm_client_isolation" ON gstr1_returns
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- gstr3b_returns
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON gstr3b_returns;
DROP POLICY IF EXISTS "firm_gstr3b_returns" ON gstr3b_returns;
CREATE POLICY "firm_client_isolation" ON gstr3b_returns
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- gstr2b_uploads
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON gstr2b_uploads;
CREATE POLICY "firm_client_isolation" ON gstr2b_uploads
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- tds_challans
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON tds_challans;
DROP POLICY IF EXISTS "firm_tds_challans" ON tds_challans;
CREATE POLICY "firm_client_isolation" ON tds_challans
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- tds_returns
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON tds_returns;
DROP POLICY IF EXISTS "firm_tds_returns" ON tds_returns;
CREATE POLICY "firm_client_isolation" ON tds_returns
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- tds_certificates
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON tds_certificates;
DROP POLICY IF EXISTS "firm_tds_certificates" ON tds_certificates;
CREATE POLICY "firm_client_isolation" ON tds_certificates
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- mca_companies
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON mca_companies;
DROP POLICY IF EXISTS "firm_mca_companies" ON mca_companies;
CREATE POLICY "firm_client_isolation" ON mca_companies
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- mca_directors
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON mca_directors;
DROP POLICY IF EXISTS "firm_mca_directors" ON mca_directors;
CREATE POLICY "firm_client_isolation" ON mca_directors
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- mca_filings
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON mca_filings;
DROP POLICY IF EXISTS "firm_mca_filings" ON mca_filings;
CREATE POLICY "firm_client_isolation" ON mca_filings
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- government_notices
-- ============================================================
DROP POLICY IF EXISTS "firm_isolation" ON public.government_notices;
CREATE POLICY "firm_client_isolation" ON public.government_notices
    FOR ALL TO authenticated
    USING (
        firm_id = get_my_firm_id()
        AND client_id IN (
            SELECT id FROM clients WHERE firm_id = get_my_firm_id()
        )
    );

-- ============================================================
-- Add return_type column to gstr1_returns if not already present
-- GSTR-9 annual returns (CGST Act §44) stored with return_type='gstr9'
-- ============================================================
ALTER TABLE gstr1_returns
    ADD COLUMN IF NOT EXISTS return_type TEXT NOT NULL DEFAULT 'gstr1';

ALTER TABLE gstr1_returns
    ADD COLUMN IF NOT EXISTS financial_year TEXT;
