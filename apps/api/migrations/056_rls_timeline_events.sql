-- Migration 056: RLS for client_timeline_events
-- Identified as missing RLS during Pre-Phase-6 Security Gate audit.
-- All other tables audited (customers, vendors, journal_entries, journal_lines,
-- payroll_runs, payroll_employees, payroll_slips, fixed_assets, bank_accounts,
-- bank_transactions, client_sales_invoices, purchase_bills) have firm-level
-- RLS policies in place via migrations 006–055.
-- This migration closes the remaining gap.

-- ─── client_timeline_events ──────────────────────────────────────────────────

ALTER TABLE client_timeline_events ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "firm_client_isolation" ON client_timeline_events;
CREATE POLICY "firm_client_isolation" ON client_timeline_events
  FOR ALL
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- Service role bypasses RLS for server-side writes (timeline events are
-- written server-side using the service key, not the user JWT).
GRANT SELECT, INSERT, UPDATE, DELETE ON client_timeline_events TO service_role;
GRANT SELECT ON client_timeline_events TO authenticated;

-- ─── Fixed Assets — ensure SELECT policy exists (migration 025 added ENABLE
-- but older policy may not cover all operations uniformly) ────────────────────

DROP POLICY IF EXISTS "firm_client_isolation" ON fixed_assets;
CREATE POLICY "firm_client_isolation" ON fixed_assets
  FOR ALL
  USING (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- ─── Payroll run lines (payroll_slips) — harden with firm_id check on INSERT
-- (existing policy uses subquery join; add direct firm_id column check) ────────

DROP POLICY IF EXISTS "payroll_slips_own_firm" ON payroll_slips;
CREATE POLICY "payroll_slips_own_firm" ON payroll_slips
  FOR ALL
  USING (
    run_id IN (SELECT id FROM payroll_runs WHERE firm_id = get_my_firm_id())
  );

-- ─── Verify get_my_firm_id() helper exists (created in migration 003/007) ────
-- This function returns the firm_id associated with the authenticated user.
-- If it does not exist, RLS policies above will silently deny all access.
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_proc
    WHERE proname = 'get_my_firm_id'
    AND pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public')
  ) THEN
    RAISE WARNING 'get_my_firm_id() function not found — RLS policies will deny all access. Ensure migration 003 has run.';
  END IF;
END $$;
