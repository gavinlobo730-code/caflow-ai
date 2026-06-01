-- CAflow AI — Migration 006: Transactions, Invoices, Bank Statements
-- Foundation for integrated accounting → GST → TDS → Compliance flow
-- All monetary values in paise (integer) — never float
-- Ref: CGST Act Section 31 (tax invoice), IT Act Section 194 (TDS)

-- ─── TRANSACTIONS ──────────────────────────────────────────────────────────
-- Master transaction table — every financial event links here
CREATE TABLE IF NOT EXISTS transactions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    firm_id         UUID NOT NULL REFERENCES firms(id),
    client_id       UUID NOT NULL REFERENCES clients(id),
    transaction_type TEXT NOT NULL CHECK (transaction_type IN (
        'sales_invoice', 'purchase_invoice', 'receipt', 'payment',
        'credit_note', 'debit_note', 'journal', 'bank_import'
    )),
    transaction_date DATE NOT NULL,
    reference_no    TEXT,
    party_name      TEXT,          -- customer name (sales) or vendor name (purchase)
    party_gstin     TEXT,
    party_pan       TEXT,
    -- Amounts — all in paise
    taxable_amount_paise    BIGINT NOT NULL DEFAULT 0,
    cgst_paise              BIGINT NOT NULL DEFAULT 0,
    sgst_paise              BIGINT NOT NULL DEFAULT 0,
    igst_paise              BIGINT NOT NULL DEFAULT 0,
    tds_paise               BIGINT NOT NULL DEFAULT 0,
    total_paise             BIGINT NOT NULL DEFAULT 0,
    -- GST details
    place_of_supply         TEXT,   -- state code e.g. "27"
    is_interstate           BOOLEAN NOT NULL DEFAULT false,
    gst_rate                NUMERIC(5,2),  -- e.g. 18.00
    hsn_sac_code            TEXT,
    -- TDS details
    tds_section             TEXT,   -- e.g. "194C", "194J"
    tds_rate                NUMERIC(5,2),
    -- Status
    status          TEXT NOT NULL DEFAULT 'draft' CHECK (status IN (
        'draft', 'posted', 'cancelled'
    )),
    journal_entry_id UUID REFERENCES journal_entries(id),
    notes           TEXT,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

-- Invoice line items (for sales/purchase invoices)
CREATE TABLE IF NOT EXISTS transaction_lines (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    transaction_id  UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
    description     TEXT NOT NULL,
    hsn_sac_code    TEXT,
    quantity        NUMERIC(10,3) NOT NULL DEFAULT 1,
    unit            TEXT DEFAULT 'NOS',
    rate_paise      BIGINT NOT NULL,       -- price per unit in paise
    taxable_paise   BIGINT NOT NULL,       -- quantity × rate
    gst_rate        NUMERIC(5,2) NOT NULL DEFAULT 0,
    cgst_paise      BIGINT NOT NULL DEFAULT 0,
    sgst_paise      BIGINT NOT NULL DEFAULT 0,
    igst_paise      BIGINT NOT NULL DEFAULT 0,
    total_paise     BIGINT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── BANK STATEMENTS ───────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS bank_statements (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    firm_id         UUID NOT NULL REFERENCES firms(id),
    client_id       UUID NOT NULL REFERENCES clients(id),
    bank_name       TEXT NOT NULL,
    account_number  TEXT,
    ifsc_code       TEXT,
    statement_from  DATE NOT NULL,
    statement_to    DATE NOT NULL,
    opening_balance_paise BIGINT NOT NULL DEFAULT 0,
    closing_balance_paise BIGINT NOT NULL DEFAULT 0,
    total_credits_paise   BIGINT NOT NULL DEFAULT 0,
    total_debits_paise    BIGINT NOT NULL DEFAULT 0,
    row_count       INTEGER NOT NULL DEFAULT 0,
    import_status   TEXT NOT NULL DEFAULT 'pending' CHECK (import_status IN (
        'pending', 'reviewed', 'posted'
    )),
    uploaded_by     UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Individual bank transactions from imported statement
CREATE TABLE IF NOT EXISTS bank_transactions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    statement_id    UUID NOT NULL REFERENCES bank_statements(id) ON DELETE CASCADE,
    firm_id         UUID NOT NULL REFERENCES firms(id),
    client_id       UUID NOT NULL REFERENCES clients(id),
    transaction_date DATE NOT NULL,
    description     TEXT NOT NULL,
    debit_paise     BIGINT NOT NULL DEFAULT 0,
    credit_paise    BIGINT NOT NULL DEFAULT 0,
    balance_paise   BIGINT,
    reference_no    TEXT,
    -- Matching
    account_id      UUID REFERENCES chart_of_accounts(id),  -- mapped account
    transaction_id  UUID REFERENCES transactions(id),        -- linked transaction
    match_status    TEXT NOT NULL DEFAULT 'unmatched' CHECK (match_status IN (
        'unmatched', 'matched', 'posted', 'ignored'
    )),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ─── COMPLIANCE CALENDAR ───────────────────────────────────────────────────
-- Auto-populated when a client with GSTIN is added
CREATE TABLE IF NOT EXISTS compliance_calendar (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    firm_id         UUID NOT NULL REFERENCES firms(id),
    client_id       UUID NOT NULL REFERENCES clients(id),
    compliance_type TEXT NOT NULL CHECK (compliance_type IN (
        'GSTR1', 'GSTR3B', 'GSTR9', 'ITR', 'TDS24Q', 'TDS26Q',
        'ADVANCE_TAX', 'TCS_RETURN', 'MCA_AOC4', 'MCA_MGT7'
    )),
    period_start    DATE NOT NULL,
    period_end      DATE NOT NULL,
    due_date        DATE NOT NULL,
    filing_status   TEXT NOT NULL DEFAULT 'pending' CHECK (filing_status IN (
        'pending', 'in_progress', 'filed', 'overdue', 'na'
    )),
    filed_date      DATE,
    arn_number      TEXT,     -- Acknowledgement Reference Number
    task_id         UUID REFERENCES tasks(id),
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (client_id, compliance_type, period_start)
);

-- ─── RLS ───────────────────────────────────────────────────────────────────
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE transaction_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank_statements ENABLE ROW LEVEL SECURITY;
ALTER TABLE bank_transactions ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_calendar ENABLE ROW LEVEL SECURITY;

CREATE POLICY "transactions_own_firm" ON transactions
    FOR ALL USING (firm_id = get_my_firm_id());

CREATE POLICY "transaction_lines_own_firm" ON transaction_lines
    FOR ALL USING (
        transaction_id IN (SELECT id FROM transactions WHERE firm_id = get_my_firm_id())
    );

CREATE POLICY "bank_statements_own_firm" ON bank_statements
    FOR ALL USING (firm_id = get_my_firm_id());

CREATE POLICY "bank_transactions_own_firm" ON bank_transactions
    FOR ALL USING (firm_id = get_my_firm_id());

CREATE POLICY "compliance_calendar_own_firm" ON compliance_calendar
    FOR ALL USING (firm_id = get_my_firm_id());

-- ─── INDEXES ───────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_transactions_client ON transactions(client_id, transaction_date) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_transactions_type ON transactions(firm_id, transaction_type, transaction_date) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_bank_txn_statement ON bank_transactions(statement_id);
CREATE INDEX IF NOT EXISTS idx_bank_txn_status ON bank_transactions(match_status) WHERE match_status = 'unmatched';
CREATE INDEX IF NOT EXISTS idx_compliance_calendar_due ON compliance_calendar(firm_id, due_date) WHERE filing_status IN ('pending', 'overdue');
CREATE INDEX IF NOT EXISTS idx_compliance_calendar_client ON compliance_calendar(client_id, compliance_type);
