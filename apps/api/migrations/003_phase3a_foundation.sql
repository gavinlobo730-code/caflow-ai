-- CAflow AI — Migration 003: Phase 3A Foundation
-- Multi-tenant firm architecture, RBAC, accounting placeholders
-- All monetary values in paise (integer) — never float

-- ─── FIRMS ─────────────────────────────────────────────────────────────────
-- Core tenant entity — everything belongs to a firm
CREATE TABLE IF NOT EXISTS firms (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            TEXT NOT NULL,
    email           TEXT NOT NULL,
    phone           TEXT,
    address_line1   TEXT,
    address_line2   TEXT,
    city            TEXT,
    state           TEXT,
    pincode         TEXT,
    gst_number      TEXT CHECK (gst_number ~ '^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]$' OR gst_number IS NULL),
    icai_mrn        TEXT,
    is_active       BOOLEAN NOT NULL DEFAULT true,
    plan            TEXT NOT NULL DEFAULT 'starter' CHECK (plan IN ('starter', 'professional', 'enterprise')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

-- ─── USERS ─────────────────────────────────────────────────────────────────
-- Replaces team_members — adds firm_id for multi-tenancy
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    firm_id         UUID NOT NULL REFERENCES firms(id),
    full_name       TEXT NOT NULL,
    email           TEXT NOT NULL,
    role            TEXT NOT NULL CHECK (role IN ('Partner', 'Manager', 'Executive', 'Reviewer', 'Client')),
    status          TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'inactive', 'invited')),
    avatar_initials TEXT,
    last_seen_at    TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ,
    UNIQUE (firm_id, email)
);

-- ─── ALTER EXISTING TABLES — ADD firm_id ───────────────────────────────────
-- Add firm_id to clients for multi-tenant isolation
ALTER TABLE clients ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id);
ALTER TABLE documents ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id);
ALTER TABLE compliance_tasks ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id);
ALTER TABLE ai_insights ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id);
ALTER TABLE activity_logs ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id);

-- ─── CLIENT — EXTENDED FIELDS ──────────────────────────────────────────────
ALTER TABLE clients ADD COLUMN IF NOT EXISTS legal_name TEXT;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS trade_name TEXT;
ALTER TABLE clients ADD COLUMN IF NOT EXISTS constitution TEXT CHECK (
    constitution IN ('Proprietorship','Partnership','LLP','Private Limited',
                     'Public Limited','Trust','Society','Individual') OR constitution IS NULL
);
ALTER TABLE clients ADD COLUMN IF NOT EXISTS assigned_manager UUID REFERENCES users(id);
ALTER TABLE clients ADD COLUMN IF NOT EXISTS assigned_executive UUID REFERENCES users(id);
ALTER TABLE clients ADD COLUMN IF NOT EXISTS onboarding_status TEXT DEFAULT 'active'
    CHECK (onboarding_status IN ('active', 'inactive', 'prospect', 'churned'));
ALTER TABLE clients ADD COLUMN IF NOT EXISTS health_score INTEGER DEFAULT 100
    CHECK (health_score BETWEEN 0 AND 100);

-- ─── COMPLIANCE RECORDS ────────────────────────────────────────────────────
-- Unified compliance record (higher-level than compliance_tasks)
CREATE TABLE IF NOT EXISTS compliance_records (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    firm_id             UUID NOT NULL REFERENCES firms(id),
    client_id           UUID NOT NULL REFERENCES clients(id),
    compliance_type     TEXT NOT NULL CHECK (compliance_type IN (
        'GST', 'Income Tax', 'TDS', 'MCA', 'Payroll', 'Bookkeeping'
    )),
    period_label        TEXT NOT NULL,          -- e.g. "May 2025", "Q4 FY 2024-25", "AY 2025-26"
    period_start        DATE NOT NULL,
    period_end          DATE NOT NULL,
    status              TEXT NOT NULL DEFAULT 'Not Started' CHECK (status IN (
        'Not Started', 'Awaiting Documents', 'In Progress',
        'Ready For Review', 'Ready To File', 'Filed', 'Overdue'
    )),
    due_date            DATE NOT NULL,
    assigned_to         UUID REFERENCES users(id),
    priority            TEXT NOT NULL DEFAULT 'medium' CHECK (priority IN ('critical','high','medium','low')),
    notes               TEXT,
    filed_date          DATE,
    acknowledgement_no  TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at          TIMESTAMPTZ
);

-- ─── TASKS — EXTENDED ─────────────────────────────────────────────────────
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS compliance_record_id UUID REFERENCES compliance_records(id);
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'Manual' CHECK (
    source IN ('Manual','GST','Income Tax','TDS','MCA','Accounting','Documents','AI')
);

-- ─── ACCOUNTING — PLACEHOLDER ENTITIES ────────────────────────────────────
-- Chart of Accounts
CREATE TABLE IF NOT EXISTS chart_of_accounts (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    firm_id         UUID NOT NULL REFERENCES firms(id),
    client_id       UUID REFERENCES clients(id),       -- NULL = firm-level template
    account_code    TEXT NOT NULL,
    account_name    TEXT NOT NULL,
    account_type    TEXT NOT NULL CHECK (account_type IN (
        'Asset', 'Liability', 'Equity', 'Revenue', 'Expense'
    )),
    account_subtype TEXT,
    parent_id       UUID REFERENCES chart_of_accounts(id),
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (firm_id, client_id, account_code)
);

-- Journal Entries (double-entry accounting)
CREATE TABLE IF NOT EXISTS journal_entries (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    firm_id         UUID NOT NULL REFERENCES firms(id),
    client_id       UUID NOT NULL REFERENCES clients(id),
    entry_date      DATE NOT NULL,
    reference_no    TEXT,
    narration       TEXT NOT NULL,
    entry_type      TEXT NOT NULL CHECK (entry_type IN (
        'Sales', 'Purchase', 'Payment', 'Receipt', 'Journal', 'Contra', 'Opening'
    )),
    is_posted       BOOLEAN NOT NULL DEFAULT false,
    posted_at       TIMESTAMPTZ,
    created_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    deleted_at      TIMESTAMPTZ
);

-- Journal Lines (debit/credit legs)
-- All amounts in paise — never float
CREATE TABLE IF NOT EXISTS journal_lines (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    journal_entry_id    UUID NOT NULL REFERENCES journal_entries(id),
    account_id          UUID NOT NULL REFERENCES chart_of_accounts(id),
    debit_paise         BIGINT NOT NULL DEFAULT 0 CHECK (debit_paise >= 0),
    credit_paise        BIGINT NOT NULL DEFAULT 0 CHECK (credit_paise >= 0),
    narration           TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Each line must be debit-only or credit-only (not both)
    CHECK (NOT (debit_paise > 0 AND credit_paise > 0))
);

-- Ledger Balances (materialized view equivalent for performance)
CREATE TABLE IF NOT EXISTS ledger_balances (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    firm_id         UUID NOT NULL REFERENCES firms(id),
    client_id       UUID NOT NULL REFERENCES clients(id),
    account_id      UUID NOT NULL REFERENCES chart_of_accounts(id),
    as_of_date      DATE NOT NULL,
    balance_paise   BIGINT NOT NULL DEFAULT 0,  -- positive = debit balance
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (client_id, account_id, as_of_date)
);

-- ─── PERMISSION GRANTS ─────────────────────────────────────────────────────
-- Explicit grants beyond default role permissions
CREATE TABLE IF NOT EXISTS permission_grants (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID NOT NULL REFERENCES users(id),
    resource_type   TEXT NOT NULL CHECK (resource_type IN (
        'client', 'compliance_record', 'document', 'task', 'report'
    )),
    resource_id     UUID,   -- NULL = grant for all of resource_type
    permission      TEXT NOT NULL CHECK (permission IN ('read', 'write', 'approve', 'admin')),
    granted_by      UUID REFERENCES users(id),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, resource_type, resource_id, permission)
);

-- ─── INDEXES ───────────────────────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_firms_active ON firms(is_active) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_users_firm ON users(firm_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_users_email ON users(email) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_clients_firm ON clients(firm_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_compliance_records_firm ON compliance_records(firm_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_compliance_records_client ON compliance_records(client_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_compliance_records_status ON compliance_records(status) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_compliance_records_due ON compliance_records(due_date) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_coa_firm ON chart_of_accounts(firm_id);
CREATE INDEX IF NOT EXISTS idx_journal_client ON journal_entries(client_id) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_journal_date ON journal_entries(entry_date) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_journal_lines_entry ON journal_lines(journal_entry_id);
CREATE INDEX IF NOT EXISTS idx_ledger_balance ON ledger_balances(client_id, account_id);

CREATE TRIGGER trg_firms_updated_at BEFORE UPDATE ON firms FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_users_updated_at BEFORE UPDATE ON users FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_compliance_records_updated_at BEFORE UPDATE ON compliance_records FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_coa_updated_at BEFORE UPDATE ON chart_of_accounts FOR EACH ROW EXECUTE FUNCTION set_updated_at();
CREATE TRIGGER trg_journal_updated_at BEFORE UPDATE ON journal_entries FOR EACH ROW EXECUTE FUNCTION set_updated_at();
