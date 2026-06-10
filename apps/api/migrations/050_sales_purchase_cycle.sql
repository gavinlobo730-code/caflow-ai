-- Sales and purchase cycle tables: invoices, receipts, credit notes, purchase bills, payments
-- All monetary values stored in integer paise to avoid floating point errors
-- GST calculations per CGST Act, 2017; TDS per IT Act, 1961

-- ============================================================
-- SALES INVOICES
-- ============================================================
-- GST invoice requirements per CGST Act Section 31 and Rule 46
CREATE TABLE IF NOT EXISTS client_sales_invoices (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  customer_id              UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  invoice_no               TEXT NOT NULL,
  invoice_date             DATE NOT NULL,
  due_date                 DATE,
  -- Place of supply state code per CGST Act Section 12/13 for IGST determination
  supply_state_code        TEXT(2),
  -- IGST applies for interstate; CGST+SGST for intrastate (CGST Act, Section 9 & IGST Act, Section 5)
  is_interstate            BOOLEAN NOT NULL DEFAULT FALSE,
  notes                    TEXT,
  -- All paise amounts are integers; never use floating point for tax calculations
  taxable_amount_paise     BIGINT NOT NULL DEFAULT 0,
  cgst_paise               BIGINT NOT NULL DEFAULT 0,
  sgst_paise               BIGINT NOT NULL DEFAULT 0,
  igst_paise               BIGINT NOT NULL DEFAULT 0,
  total_gst_paise          BIGINT NOT NULL DEFAULT 0,
  total_paise              BIGINT NOT NULL DEFAULT 0,
  status                   TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft','issued','partially_paid','paid','cancelled')),
  -- journal_entry_id left as nullable UUID with no FK since journal_entries table may not exist yet
  journal_entry_id         UUID,
  created_by               UUID,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (firm_id, invoice_no)
);

CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_client_id ON client_sales_invoices(client_id);
CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_customer_id ON client_sales_invoices(customer_id);
CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_firm_id_status ON client_sales_invoices(firm_id, status);
CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_invoice_date ON client_sales_invoices(invoice_date);

ALTER TABLE client_sales_invoices ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_client_sales_invoices" ON client_sales_invoices
  FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON client_sales_invoices TO authenticated;


-- ============================================================
-- SALES INVOICE LINES
-- ============================================================
-- HSN/SAC code required on invoices per CGST Rule 46(h)
-- gst_rate_bps: rate in basis points (1800 = 18.00%) — integer, never float
CREATE TABLE IF NOT EXISTS client_sales_invoice_lines (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  sales_invoice_id         UUID NOT NULL REFERENCES client_sales_invoices(id) ON DELETE CASCADE,
  description              TEXT NOT NULL,
  hsn_sac                  TEXT,  -- HSN for goods, SAC for services (CGST Rule 46)
  quantity                 NUMERIC(10,3) NOT NULL DEFAULT 1,
  unit                     TEXT,
  rate_paise               BIGINT NOT NULL DEFAULT 0,
  taxable_amount_paise     BIGINT NOT NULL DEFAULT 0,
  -- GST rate in basis points: 1800 = 18.00% (CGST Act, Schedule I-IV)
  gst_rate_bps             INTEGER NOT NULL DEFAULT 1800,
  cgst_paise               BIGINT NOT NULL DEFAULT 0,
  sgst_paise               BIGINT NOT NULL DEFAULT 0,
  igst_paise               BIGINT NOT NULL DEFAULT 0,
  line_total_paise         BIGINT NOT NULL DEFAULT 0,
  sort_order               INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_client_sales_invoice_lines_invoice_id ON client_sales_invoice_lines(sales_invoice_id);

ALTER TABLE client_sales_invoice_lines ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_client_sales_invoice_lines" ON client_sales_invoice_lines
  FOR ALL TO authenticated
  USING (sales_invoice_id IN (
    SELECT id FROM client_sales_invoices WHERE firm_id = get_my_firm_id()
  ));

GRANT SELECT, INSERT, UPDATE, DELETE ON client_sales_invoice_lines TO authenticated;


-- ============================================================
-- RECEIPTS
-- ============================================================
CREATE TABLE IF NOT EXISTS receipts (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  customer_id              UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  receipt_no               TEXT NOT NULL,
  receipt_date             DATE NOT NULL,
  -- All monetary values in integer paise
  amount_paise             BIGINT NOT NULL DEFAULT 0,
  payment_mode             TEXT NOT NULL DEFAULT 'bank'
                             CHECK (payment_mode IN ('bank','cash','cheque','upi','neft','rtgs')),
  reference_no             TEXT,
  notes                    TEXT,
  allocated_paise          BIGINT NOT NULL DEFAULT 0,
  -- unallocated = amount - allocated; maintained at application layer
  unallocated_paise        BIGINT NOT NULL DEFAULT 0,
  journal_entry_id         UUID,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_receipts_client_id ON receipts(client_id);
CREATE INDEX IF NOT EXISTS idx_receipts_customer_id ON receipts(customer_id);
CREATE INDEX IF NOT EXISTS idx_receipts_firm_id_date ON receipts(firm_id, receipt_date);

ALTER TABLE receipts ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_receipts" ON receipts
  FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON receipts TO authenticated;


-- ============================================================
-- RECEIPT ALLOCATIONS
-- ============================================================
CREATE TABLE IF NOT EXISTS receipt_allocations (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  receipt_id               UUID NOT NULL REFERENCES receipts(id) ON DELETE CASCADE,
  sales_invoice_id         UUID NOT NULL REFERENCES client_sales_invoices(id) ON DELETE CASCADE,
  allocated_paise          BIGINT NOT NULL DEFAULT 0,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (receipt_id, sales_invoice_id)
);

CREATE INDEX IF NOT EXISTS idx_receipt_allocations_receipt_id ON receipt_allocations(receipt_id);
CREATE INDEX IF NOT EXISTS idx_receipt_allocations_invoice_id ON receipt_allocations(sales_invoice_id);

ALTER TABLE receipt_allocations ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_receipt_allocations" ON receipt_allocations
  FOR ALL TO authenticated
  USING (receipt_id IN (
    SELECT id FROM receipts WHERE firm_id = get_my_firm_id()
  ));

GRANT SELECT, INSERT, UPDATE, DELETE ON receipt_allocations TO authenticated;


-- ============================================================
-- CREDIT NOTES
-- ============================================================
-- Credit notes per CGST Act Section 34 — issued for returns, price adjustments, post-sale discounts
CREATE TABLE IF NOT EXISTS credit_notes (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  customer_id              UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,
  -- nullable: CN may not link to a specific invoice (CGST Act Section 34)
  sales_invoice_id         UUID REFERENCES client_sales_invoices(id),
  credit_note_no           TEXT NOT NULL,
  credit_note_date         DATE NOT NULL,
  reason                   TEXT,
  taxable_amount_paise     BIGINT NOT NULL DEFAULT 0,
  cgst_paise               BIGINT NOT NULL DEFAULT 0,
  sgst_paise               BIGINT NOT NULL DEFAULT 0,
  igst_paise               BIGINT NOT NULL DEFAULT 0,
  total_paise              BIGINT NOT NULL DEFAULT 0,
  status                   TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft','issued','applied')),
  journal_entry_id         UUID,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (firm_id, credit_note_no)
);

CREATE INDEX IF NOT EXISTS idx_credit_notes_client_id ON credit_notes(client_id);
CREATE INDEX IF NOT EXISTS idx_credit_notes_customer_id ON credit_notes(customer_id);
CREATE INDEX IF NOT EXISTS idx_credit_notes_firm_id_status ON credit_notes(firm_id, status);

ALTER TABLE credit_notes ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_credit_notes" ON credit_notes
  FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON credit_notes TO authenticated;


-- ============================================================
-- CREDIT NOTE LINES
-- ============================================================
CREATE TABLE IF NOT EXISTS credit_note_lines (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  credit_note_id           UUID NOT NULL REFERENCES credit_notes(id) ON DELETE CASCADE,
  description              TEXT NOT NULL,
  hsn_sac                  TEXT,
  quantity                 NUMERIC(10,3) NOT NULL DEFAULT 1,
  rate_paise               BIGINT NOT NULL DEFAULT 0,
  taxable_amount_paise     BIGINT NOT NULL DEFAULT 0,
  -- GST rate in basis points: 1800 = 18.00% (CGST Act, Schedule I-IV)
  gst_rate_bps             INTEGER NOT NULL DEFAULT 1800,
  cgst_paise               BIGINT NOT NULL DEFAULT 0,
  sgst_paise               BIGINT NOT NULL DEFAULT 0,
  igst_paise               BIGINT NOT NULL DEFAULT 0,
  line_total_paise         BIGINT NOT NULL DEFAULT 0,
  sort_order               INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_credit_note_lines_credit_note_id ON credit_note_lines(credit_note_id);

ALTER TABLE credit_note_lines ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_credit_note_lines" ON credit_note_lines
  FOR ALL TO authenticated
  USING (credit_note_id IN (
    SELECT id FROM credit_notes WHERE firm_id = get_my_firm_id()
  ));

GRANT SELECT, INSERT, UPDATE, DELETE ON credit_note_lines TO authenticated;


-- ============================================================
-- PURCHASE BILLS
-- ============================================================
-- Input tax credit eligibility per CGST Act Section 16; TDS deduction per IT Act Section 194C/194I/194J
CREATE TABLE IF NOT EXISTS purchase_bills (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  vendor_id                UUID NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
  bill_no                  TEXT,  -- vendor's own invoice number
  our_reference            TEXT,
  bill_date                DATE NOT NULL,
  due_date                 DATE,
  taxable_amount_paise     BIGINT NOT NULL DEFAULT 0,
  cgst_paise               BIGINT NOT NULL DEFAULT 0,
  sgst_paise               BIGINT NOT NULL DEFAULT 0,
  igst_paise               BIGINT NOT NULL DEFAULT 0,
  total_gst_paise          BIGINT NOT NULL DEFAULT 0,
  total_paise              BIGINT NOT NULL DEFAULT 0,
  -- TDS deduction at source per IT Act Section 194C/194I/194J — integer paise, never float
  tds_paise                BIGINT NOT NULL DEFAULT 0,
  tds_section              TEXT,     -- e.g. '194C', '194I', '194J'
  tds_rate_bps             INTEGER NOT NULL DEFAULT 0,  -- basis points: 1000 = 10.00%
  -- net_payable = total_paise - tds_paise
  net_payable_paise        BIGINT NOT NULL DEFAULT 0,
  status                   TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft','received','partially_paid','paid','cancelled')),
  document_url             TEXT,
  -- AI extraction flag for bill OCR/parsing feature
  is_ai_extracted          BOOLEAN NOT NULL DEFAULT FALSE,
  ai_extraction_data       JSONB,
  journal_entry_id         UUID,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_purchase_bills_client_id ON purchase_bills(client_id);
CREATE INDEX IF NOT EXISTS idx_purchase_bills_vendor_id ON purchase_bills(vendor_id);
CREATE INDEX IF NOT EXISTS idx_purchase_bills_firm_id_status ON purchase_bills(firm_id, status);
CREATE INDEX IF NOT EXISTS idx_purchase_bills_bill_date ON purchase_bills(bill_date);

ALTER TABLE purchase_bills ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_purchase_bills" ON purchase_bills
  FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON purchase_bills TO authenticated;


-- ============================================================
-- PURCHASE BILL LINES
-- ============================================================
CREATE TABLE IF NOT EXISTS purchase_bill_lines (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  purchase_bill_id         UUID NOT NULL REFERENCES purchase_bills(id) ON DELETE CASCADE,
  description              TEXT NOT NULL,
  hsn_sac                  TEXT,
  expense_account_id       UUID,  -- nullable reference to chart of accounts
  quantity                 NUMERIC(10,3) NOT NULL DEFAULT 1,
  rate_paise               BIGINT NOT NULL DEFAULT 0,
  taxable_amount_paise     BIGINT NOT NULL DEFAULT 0,
  -- GST rate in basis points: 1800 = 18.00% (CGST Act, Schedule I-IV)
  gst_rate_bps             INTEGER NOT NULL DEFAULT 1800,
  cgst_paise               BIGINT NOT NULL DEFAULT 0,
  sgst_paise               BIGINT NOT NULL DEFAULT 0,
  igst_paise               BIGINT NOT NULL DEFAULT 0,
  line_total_paise         BIGINT NOT NULL DEFAULT 0,
  sort_order               INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_purchase_bill_lines_bill_id ON purchase_bill_lines(purchase_bill_id);

ALTER TABLE purchase_bill_lines ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_purchase_bill_lines" ON purchase_bill_lines
  FOR ALL TO authenticated
  USING (purchase_bill_id IN (
    SELECT id FROM purchase_bills WHERE firm_id = get_my_firm_id()
  ));

GRANT SELECT, INSERT, UPDATE, DELETE ON purchase_bill_lines TO authenticated;


-- ============================================================
-- PURCHASE PAYMENTS
-- ============================================================
-- purchase_bill_id nullable to support advance payments before bill receipt
CREATE TABLE IF NOT EXISTS purchase_payments (
  id                       UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id                UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  vendor_id                UUID NOT NULL REFERENCES vendors(id) ON DELETE CASCADE,
  -- nullable: advance payments may not be linked to a specific bill
  purchase_bill_id         UUID REFERENCES purchase_bills(id),
  payment_no               TEXT NOT NULL,
  payment_date             DATE NOT NULL,
  amount_paise             BIGINT NOT NULL DEFAULT 0,
  payment_mode             TEXT NOT NULL DEFAULT 'bank'
                             CHECK (payment_mode IN ('bank','cash','cheque','upi','neft','rtgs')),
  reference_no             TEXT,
  notes                    TEXT,
  journal_entry_id         UUID,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_purchase_payments_client_id ON purchase_payments(client_id);
CREATE INDEX IF NOT EXISTS idx_purchase_payments_vendor_id ON purchase_payments(vendor_id);
CREATE INDEX IF NOT EXISTS idx_purchase_payments_firm_id_date ON purchase_payments(firm_id, payment_date);
CREATE INDEX IF NOT EXISTS idx_purchase_payments_bill_id ON purchase_payments(purchase_bill_id);

ALTER TABLE purchase_payments ENABLE ROW LEVEL SECURITY;

CREATE POLICY "firm_purchase_payments" ON purchase_payments
  FOR ALL TO authenticated
  USING (firm_id = get_my_firm_id());

GRANT SELECT, INSERT, UPDATE, DELETE ON purchase_payments TO authenticated;
