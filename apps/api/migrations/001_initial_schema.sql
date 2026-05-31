-- CAflow AI — Initial Schema Migration
-- All monetary values stored in paise (integer) to avoid floating point errors
-- Ref: Indian tax domain rules in CLAUDE.md

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ─── TEAM MEMBERS ──────────────────────────────────────────────────────────
CREATE TABLE team_members (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('owner', 'manager', 'staff', 'viewer')),
    is_active BOOLEAN NOT NULL DEFAULT true,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- ─── CLIENTS ───────────────────────────────────────────────────────────────
CREATE TABLE clients (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_name TEXT NOT NULL,
    entity_type TEXT NOT NULL CHECK (entity_type IN (
        'Proprietorship', 'Partnership', 'LLP', 'Private Limited',
        'Public Limited', 'Trust', 'Society', 'Individual'
    )),
    pan TEXT NOT NULL CHECK (pan ~ '^[A-Z]{5}[0-9]{4}[A-Z]$'),
    gstin TEXT CHECK (gstin ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$'),
    mobile TEXT,
    email TEXT,
    address_line1 TEXT,
    address_line2 TEXT,
    city TEXT,
    state TEXT,
    pincode TEXT,
    state_code TEXT,
    financial_year_start DATE,
    financial_year_end DATE,
    gst_registration_date DATE,
    gst_filing_frequency TEXT CHECK (gst_filing_frequency IN ('monthly', 'quarterly')),
    assigned_to UUID REFERENCES team_members(id),
    status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive')),
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- ─── DOCUMENTS ─────────────────────────────────────────────────────────────
CREATE TABLE documents (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id),
    document_type TEXT NOT NULL CHECK (document_type IN (
        'FORM16', 'GST_INVOICE', 'BANK_STATEMENT', 'AIS',
        'FORM26AS', 'TDS_CERTIFICATE', 'RENTAL_AGREEMENT',
        'CAPITAL_GAINS_STATEMENT', 'OTHER'
    )),
    file_name TEXT NOT NULL,
    file_path TEXT NOT NULL,
    file_size_bytes INTEGER,
    mime_type TEXT,
    financial_year TEXT,
    upload_date TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    extracted_json JSONB,
    confidence_score NUMERIC(5,4) CHECK (confidence_score BETWEEN 0 AND 1),
    review_status TEXT NOT NULL DEFAULT 'pending_review'
        CHECK (review_status IN ('pending_review', 'approved', 'rejected')),
    reviewed_by UUID REFERENCES team_members(id),
    reviewed_at TIMESTAMPTZ,
    uploaded_by UUID REFERENCES team_members(id),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- ─── COMPLIANCE TASKS ──────────────────────────────────────────────────────
CREATE TABLE compliance_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id),
    compliance_type TEXT NOT NULL CHECK (compliance_type IN (
        'GSTR1', 'GSTR3B', 'GSTR9', 'ITR', 'TDS24Q', 'TDS26Q',
        'ADVANCE_TAX', 'TCS_RETURN', 'OTHER'
    )),
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    due_date DATE NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'in_progress', 'filed', 'overdue', 'not_applicable')),
    priority TEXT NOT NULL DEFAULT 'medium'
        CHECK (priority IN ('critical', 'high', 'medium', 'low')),
    assigned_to UUID REFERENCES team_members(id),
    filing_id UUID,  -- FK to filings added after that table is created
    notes TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- ─── FILINGS ───────────────────────────────────────────────────────────────
CREATE TABLE filings (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id),
    compliance_task_id UUID REFERENCES compliance_tasks(id),
    filing_type TEXT NOT NULL,
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    filed_date DATE,
    acknowledgement_number TEXT,
    -- All tax values in paise (integer arithmetic only)
    tax_payable_paise BIGINT,
    tax_paid_paise BIGINT,
    late_fee_paise BIGINT,
    interest_paise BIGINT,
    filed_by UUID REFERENCES team_members(id),
    status TEXT NOT NULL DEFAULT 'draft'
        CHECK (status IN ('draft', 'ready', 'filed', 'revised')),
    filing_data JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- Add FK from compliance_tasks to filings now that filings table exists
ALTER TABLE compliance_tasks
    ADD CONSTRAINT fk_compliance_filing
    FOREIGN KEY (filing_id) REFERENCES filings(id);

-- ─── ACTIVITY LOGS ─────────────────────────────────────────────────────────
CREATE TABLE activity_logs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID REFERENCES clients(id),
    actor_id UUID REFERENCES team_members(id),
    action TEXT NOT NULL CHECK (action IN (
        'client_created', 'client_updated',
        'document_uploaded', 'document_approved', 'document_rejected',
        'compliance_task_created', 'compliance_task_updated',
        'filing_prepared', 'filing_submitted',
        'reminder_sent', 'ai_insight_generated',
        'note_added', 'team_assigned'
    )),
    entity_type TEXT,
    entity_id UUID,
    description TEXT NOT NULL,
    metadata JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- Activity logs are immutable — no updated_at, no soft delete
);

-- ─── AI INSIGHTS ───────────────────────────────────────────────────────────
CREATE TABLE ai_insights (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    client_id UUID NOT NULL REFERENCES clients(id),
    insight_type TEXT NOT NULL CHECK (insight_type IN (
        'MISSING_INVOICE', 'TDS_MISMATCH', 'DEADLINE_APPROACHING',
        'ITC_MISMATCH', 'TURNOVER_THRESHOLD', 'PAYMENT_DELAY',
        'RECONCILIATION_GAP', 'OTHER'
    )),
    severity TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    recommended_action TEXT,
    related_entity_type TEXT,
    related_entity_id UUID,
    status TEXT NOT NULL DEFAULT 'open'
        CHECK (status IN ('open', 'acknowledged', 'resolved', 'dismissed')),
    resolved_by UUID REFERENCES team_members(id),
    resolved_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at TIMESTAMPTZ
);

-- ─── INDEXES ───────────────────────────────────────────────────────────────
CREATE INDEX idx_clients_pan ON clients(pan) WHERE deleted_at IS NULL;
CREATE INDEX idx_clients_gstin ON clients(gstin) WHERE deleted_at IS NULL;
CREATE INDEX idx_clients_status ON clients(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_client ON documents(client_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_documents_type ON documents(document_type) WHERE deleted_at IS NULL;
CREATE INDEX idx_compliance_client ON compliance_tasks(client_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_compliance_due_date ON compliance_tasks(due_date) WHERE deleted_at IS NULL;
CREATE INDEX idx_compliance_status ON compliance_tasks(status) WHERE deleted_at IS NULL;
CREATE INDEX idx_filings_client ON filings(client_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_activity_client ON activity_logs(client_id);
CREATE INDEX idx_activity_created ON activity_logs(created_at DESC);
CREATE INDEX idx_insights_client ON ai_insights(client_id) WHERE deleted_at IS NULL;
CREATE INDEX idx_insights_status ON ai_insights(status) WHERE deleted_at IS NULL;

-- ─── UPDATED_AT TRIGGER ────────────────────────────────────────────────────
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_clients_updated_at BEFORE UPDATE ON clients FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_documents_updated_at BEFORE UPDATE ON documents FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_compliance_updated_at BEFORE UPDATE ON compliance_tasks FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_filings_updated_at BEFORE UPDATE ON filings FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_insights_updated_at BEFORE UPDATE ON ai_insights FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_team_updated_at BEFORE UPDATE ON team_members FOR EACH ROW EXECUTE FUNCTION set_updated_at();
