-- Migration 007: RLS hardening, missing columns, and permission loop fixes
-- Run this AFTER confirming your auth_user_id is set in the users table

-- ─── ENSURE firm_id EXISTS ON ALL CORE TABLES ────────────────────────────────

ALTER TABLE tasks              ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id);
ALTER TABLE clients            ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id);
ALTER TABLE compliance_tasks   ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id);
ALTER TABLE documents          ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id);
ALTER TABLE journal_entries    ADD COLUMN IF NOT EXISTS firm_id UUID REFERENCES firms(id);

-- ─── RECREATE get_my_firm_id WITH SECURITY DEFINER ───────────────────────────
-- SECURITY DEFINER runs as the function owner (postgres), bypassing RLS on the
-- users table lookup itself — this prevents the "permission denied for table users"
-- loop that occurs when the users table has RLS enabled.

CREATE OR REPLACE FUNCTION get_my_firm_id()
RETURNS UUID
LANGUAGE SQL
SECURITY DEFINER
STABLE
AS $$
  SELECT firm_id FROM users WHERE auth_user_id = auth.uid() LIMIT 1;
$$;

-- Grant execute to authenticated users
GRANT EXECUTE ON FUNCTION get_my_firm_id() TO authenticated;

-- ─── ENSURE users TABLE HAS RLS BUT ALLOWS SELF-READ ────────────────────────

ALTER TABLE users ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "users_own_row" ON users;
CREATE POLICY "users_own_row" ON users
  FOR ALL USING (auth_user_id = auth.uid());

-- ─── REFRESH ALL TABLE RLS POLICIES ─────────────────────────────────────────

-- firms
ALTER TABLE firms ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "firms_own" ON firms;
CREATE POLICY "firms_own" ON firms
  FOR ALL USING (id = get_my_firm_id());

-- clients
ALTER TABLE clients ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "clients_own_firm" ON clients;
CREATE POLICY "clients_own_firm" ON clients
  FOR ALL USING (firm_id = get_my_firm_id());

-- tasks
ALTER TABLE tasks ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "tasks_own_firm" ON tasks;
CREATE POLICY "tasks_own_firm" ON tasks
  FOR ALL USING (firm_id = get_my_firm_id());

-- compliance_calendar (from migration 006)
ALTER TABLE compliance_calendar ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "compliance_calendar_own_firm" ON compliance_calendar;
CREATE POLICY "compliance_calendar_own_firm" ON compliance_calendar
  FOR ALL USING (firm_id = get_my_firm_id());

-- transactions (from migration 006)
ALTER TABLE transactions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "transactions_own_firm" ON transactions;
CREATE POLICY "transactions_own_firm" ON transactions
  FOR ALL USING (firm_id = get_my_firm_id());

-- transaction_lines (from migration 006)
ALTER TABLE transaction_lines ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "transaction_lines_own_firm" ON transaction_lines;
CREATE POLICY "transaction_lines_own_firm" ON transaction_lines
  FOR ALL USING (
    transaction_id IN (
      SELECT id FROM transactions WHERE firm_id = get_my_firm_id()
    )
  );

-- bank_statements (from migration 006)
ALTER TABLE bank_statements ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "bank_statements_own_firm" ON bank_statements;
CREATE POLICY "bank_statements_own_firm" ON bank_statements
  FOR ALL USING (firm_id = get_my_firm_id());

-- bank_transactions (from migration 006)
ALTER TABLE bank_transactions ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "bank_transactions_own_firm" ON bank_transactions;
CREATE POLICY "bank_transactions_own_firm" ON bank_transactions
  FOR ALL USING (firm_id = get_my_firm_id());

-- journal_entries
ALTER TABLE journal_entries ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "journal_entries_own_firm" ON journal_entries;
CREATE POLICY "journal_entries_own_firm" ON journal_entries
  FOR ALL USING (firm_id = get_my_firm_id());

-- documents
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "documents_own_firm" ON documents;
CREATE POLICY "documents_own_firm" ON documents
  FOR ALL USING (firm_id = get_my_firm_id());

-- ─── VERIFY ──────────────────────────────────────────────────────────────────
-- Run this after to confirm your session works:
-- SELECT get_my_firm_id();
-- Should return your firm UUID, not NULL.
