-- CAflow AI — Migration 005: Supabase Auth Linkage, Storage Paths, RLS
-- Connects platform tables to Supabase auth.users
-- Enables Row Level Security with firm_id isolation
-- All monetary values remain in paise (integer)

-- ─── AUTH LINKAGE ──────────────────────────────────────────────────────────
-- Link our users table to Supabase auth.users
ALTER TABLE users ADD COLUMN IF NOT EXISTS auth_user_id UUID REFERENCES auth.users(id) ON DELETE SET NULL;
CREATE UNIQUE INDEX IF NOT EXISTS users_auth_user_id_idx ON users(auth_user_id) WHERE auth_user_id IS NOT NULL;

-- ─── STORAGE PATH ──────────────────────────────────────────────────────────
-- Add Supabase Storage object path to documents
-- Format: {firm_id}/{client_id}/{document_type}/{uuid}_{filename}
ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_path TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS storage_bucket TEXT DEFAULT 'Documents';

-- ─── ENABLE RLS ON ALL TENANT TABLES ──────────────────────────────────────
ALTER TABLE firms ENABLE ROW LEVEL SECURITY;
ALTER TABLE users ENABLE ROW LEVEL SECURITY;
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE compliance_records ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_entries ENABLE ROW LEVEL SECURITY;
ALTER TABLE journal_lines ENABLE ROW LEVEL SECURITY;
ALTER TABLE ledger_balances ENABLE ROW LEVEL SECURITY;
ALTER TABLE chart_of_accounts ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_extractions ENABLE ROW LEVEL SECURITY;
ALTER TABLE document_risks ENABLE ROW LEVEL SECURITY;
ALTER TABLE automation_rules ENABLE ROW LEVEL SECURITY;
ALTER TABLE automation_executions ENABLE ROW LEVEL SECURITY;
ALTER TABLE notifications ENABLE ROW LEVEL SECURITY;
ALTER TABLE activity_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE ai_insights ENABLE ROW LEVEL SECURITY;
ALTER TABLE workflows ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
ALTER TABLE reminders ENABLE ROW LEVEL SECURITY;

-- ─── HELPER FUNCTION — get firm_id for the current auth user ───────────────
CREATE OR REPLACE FUNCTION get_my_firm_id()
RETURNS UUID AS $$
  SELECT firm_id FROM users WHERE auth_user_id = auth.uid() LIMIT 1;
$$ LANGUAGE SQL SECURITY DEFINER STABLE;

-- ─── RLS POLICIES — FIRMS ──────────────────────────────────────────────────
DROP POLICY IF EXISTS "firms_own" ON firms;
CREATE POLICY "firms_own" ON firms
  FOR ALL USING (id = get_my_firm_id());

-- ─── RLS POLICIES — USERS ─────────────────────────────────────────────────
DROP POLICY IF EXISTS "users_own_firm" ON users;
CREATE POLICY "users_own_firm" ON users
  FOR ALL USING (firm_id = get_my_firm_id());

-- ─── RLS POLICIES — CLIENTS ───────────────────────────────────────────────
DROP POLICY IF EXISTS "clients_own_firm" ON clients;
CREATE POLICY "clients_own_firm" ON clients
  FOR ALL USING (firm_id = get_my_firm_id());

-- ─── RLS POLICIES — DOCUMENTS ─────────────────────────────────────────────
DROP POLICY IF EXISTS "documents_own_firm" ON documents;
CREATE POLICY "documents_own_firm" ON documents
  FOR ALL USING (firm_id = get_my_firm_id());

-- ─── RLS POLICIES — TASKS ─────────────────────────────────────────────────
DROP POLICY IF EXISTS "tasks_own_firm" ON tasks;
CREATE POLICY "tasks_own_firm" ON tasks
  FOR ALL USING (firm_id = get_my_firm_id());

-- ─── RLS POLICIES — COMPLIANCE TASKS ──────────────────────────────────────
DROP POLICY IF EXISTS "compliance_tasks_own_firm" ON compliance_tasks;
CREATE POLICY "compliance_tasks_own_firm" ON compliance_tasks
  FOR ALL USING (firm_id = get_my_firm_id());

-- ─── RLS POLICIES — COMPLIANCE RECORDS ────────────────────────────────────
DROP POLICY IF EXISTS "compliance_records_own_firm" ON compliance_records;
CREATE POLICY "compliance_records_own_firm" ON compliance_records
  FOR ALL USING (firm_id = get_my_firm_id());

-- ─── RLS POLICIES — ACCOUNTING ────────────────────────────────────────────
DROP POLICY IF EXISTS "journal_entries_own_firm" ON journal_entries;
CREATE POLICY "journal_entries_own_firm" ON journal_entries
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "chart_of_accounts_own_firm" ON chart_of_accounts;
CREATE POLICY "chart_of_accounts_own_firm" ON chart_of_accounts
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "ledger_balances_own_firm" ON ledger_balances;
CREATE POLICY "ledger_balances_own_firm" ON ledger_balances
  FOR ALL USING (firm_id = get_my_firm_id());

-- ─── RLS POLICIES — INTELLIGENCE TABLES ───────────────────────────────────
DROP POLICY IF EXISTS "document_extractions_own_firm" ON document_extractions;
CREATE POLICY "document_extractions_own_firm" ON document_extractions
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "document_risks_own_firm" ON document_risks;
CREATE POLICY "document_risks_own_firm" ON document_risks
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "automation_rules_own_firm" ON automation_rules;
CREATE POLICY "automation_rules_own_firm" ON automation_rules
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "notifications_own_firm" ON notifications;
CREATE POLICY "notifications_own_firm" ON notifications
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "ai_insights_own_firm" ON ai_insights;
CREATE POLICY "ai_insights_own_firm" ON ai_insights
  FOR ALL USING (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "activity_logs_own_firm" ON activity_logs;
CREATE POLICY "activity_logs_own_firm" ON activity_logs
  FOR ALL USING (firm_id = get_my_firm_id());

-- ─── STORAGE RLS — Documents bucket ───────────────────────────────────────
-- Users can only access files in their firm's folder
-- Bucket path: {firm_id}/{client_id}/{type}/{filename}

INSERT INTO storage.buckets (id, name, public)
VALUES ('Documents', 'Documents', false)
ON CONFLICT (id) DO NOTHING;

DROP POLICY IF EXISTS "documents_storage_select" ON storage.objects;
CREATE POLICY "documents_storage_select" ON storage.objects
  FOR SELECT USING (
    bucket_id = 'Documents'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
  );

DROP POLICY IF EXISTS "documents_storage_insert" ON storage.objects;
CREATE POLICY "documents_storage_insert" ON storage.objects
  FOR INSERT WITH CHECK (
    bucket_id = 'Documents'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
  );

DROP POLICY IF EXISTS "documents_storage_delete" ON storage.objects;
CREATE POLICY "documents_storage_delete" ON storage.objects
  FOR DELETE USING (
    bucket_id = 'Documents'
    AND (storage.foldername(name))[1] = get_my_firm_id()::text
  );
