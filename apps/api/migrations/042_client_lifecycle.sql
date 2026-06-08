-- Migration 042: Client lifecycle management
-- Adds archived status, is_test flag, and hardens RLS to exclude soft-deleted rows.
-- No destructive changes — all existing data is preserved as-is.

-- ─── 1. Extend status CHECK to include 'archived' ─────────────────────────
ALTER TABLE clients DROP CONSTRAINT IF EXISTS clients_status_check;
ALTER TABLE clients ADD CONSTRAINT clients_status_check
    CHECK (status IN ('active', 'inactive', 'archived'));

-- ─── 2. Add is_test flag ───────────────────────────────────────────────────
ALTER TABLE clients ADD COLUMN IF NOT EXISTS is_test BOOLEAN NOT NULL DEFAULT false;

-- ─── 3. Tighten RLS: exclude soft-deleted rows from all Supabase JS access ─
-- The existing policy allows any row where firm_id matches.
-- We add deleted_at IS NULL so soft-deleted clients are invisible even via
-- direct Supabase client access (not just via the API repo layer).
DROP POLICY IF EXISTS "clients_own_firm" ON clients;
CREATE POLICY "clients_own_firm" ON clients
    FOR ALL USING (
        firm_id = get_my_firm_id()
        AND deleted_at IS NULL
    );

-- ─── 4. Index for is_test and archived queries ────────────────────────────
CREATE INDEX IF NOT EXISTS idx_clients_is_test  ON clients(firm_id, is_test) WHERE deleted_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_clients_archived ON clients(firm_id, status)  WHERE deleted_at IS NULL;
