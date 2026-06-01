-- CAflow AI — Migration 004: Document Intelligence, Risk Engine, Automation, Notifications

-- Document extraction results
CREATE TABLE IF NOT EXISTS document_extractions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID NOT NULL REFERENCES documents(id),
    firm_id         UUID REFERENCES firms(id),
    extraction_status TEXT NOT NULL DEFAULT 'pending' CHECK (extraction_status IN (
        'pending', 'processing', 'completed', 'failed'
    )),
    provider        TEXT DEFAULT 'mock' CHECK (provider IN ('mock', 'aws_textract', 'google_docai', 'azure_formrec', 'claude_vision')),
    confidence_score NUMERIC(4,3),  -- 0.000 to 1.000
    extracted_data  JSONB,
    validation_results JSONB,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Document-level risks
CREATE TABLE IF NOT EXISTS document_risks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID NOT NULL REFERENCES documents(id),
    client_id       UUID NOT NULL REFERENCES clients(id),
    firm_id         UUID REFERENCES firms(id),
    severity        TEXT NOT NULL CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    category        TEXT NOT NULL CHECK (category IN (
        'AIS_MISMATCH', 'TDS_MISMATCH', 'MISSING_INVOICE', 'GST_MISMATCH',
        'BANK_RECONCILIATION', 'HIGH_LIABILITY', 'MISSING_FORM16', 'MCA_OVERDUE',
        'DUPLICATE_ENTRY', 'CLASSIFICATION_ERROR', 'OTHER'
    )),
    title           TEXT NOT NULL,
    description     TEXT NOT NULL,
    resolution_status TEXT NOT NULL DEFAULT 'open' CHECK (resolution_status IN ('open', 'acknowledged', 'resolved', 'false_positive')),
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Automation rules
CREATE TABLE IF NOT EXISTS automation_rules (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    firm_id         UUID REFERENCES firms(id),
    name            TEXT NOT NULL,
    trigger_type    TEXT NOT NULL CHECK (trigger_type IN (
        'risk_detected', 'document_uploaded', 'compliance_due', 'status_changed', 'deadline_approaching'
    )),
    trigger_config  JSONB NOT NULL DEFAULT '{}',
    action_type     TEXT NOT NULL CHECK (action_type IN (
        'create_task', 'send_notification', 'update_status', 'assign_user', 'create_insight'
    )),
    action_config   JSONB NOT NULL DEFAULT '{}',
    is_enabled      BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Automation execution log
CREATE TABLE IF NOT EXISTS automation_executions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    rule_id         UUID NOT NULL REFERENCES automation_rules(id),
    trigger_data    JSONB,
    status          TEXT NOT NULL CHECK (status IN ('success', 'failed', 'skipped')),
    result_data     JSONB,
    error_message   TEXT,
    executed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Notifications
CREATE TABLE IF NOT EXISTS notifications (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    firm_id         UUID REFERENCES firms(id),
    user_id         UUID REFERENCES users(id),
    client_id       UUID REFERENCES clients(id),
    type            TEXT NOT NULL CHECK (type IN (
        'task_assigned', 'risk_detected', 'document_processed',
        'compliance_due', 'ai_recommendation', 'status_changed'
    )),
    title           TEXT NOT NULL,
    body            TEXT NOT NULL,
    severity        TEXT NOT NULL DEFAULT 'info' CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    is_read         BOOLEAN NOT NULL DEFAULT false,
    action_url      TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_extractions_document ON document_extractions(document_id);
CREATE INDEX IF NOT EXISTS idx_doc_risks_client ON document_risks(client_id) WHERE resolution_status = 'open';
CREATE INDEX IF NOT EXISTS idx_doc_risks_severity ON document_risks(severity) WHERE resolution_status = 'open';
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id) WHERE is_read = false;
CREATE INDEX IF NOT EXISTS idx_notifications_firm ON notifications(firm_id);
CREATE INDEX IF NOT EXISTS idx_automation_rules_firm ON automation_rules(firm_id) WHERE is_enabled = true;
