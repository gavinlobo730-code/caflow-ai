-- PracticeSync AI — Migration 075: Billing Traceability & Idempotency
-- Amendment v1.1 (Phase 10B) — BATCH 3 (Revenue Operations).
--
-- Adds traceability + duplicate-invoice safety to the EXISTING sales-invoice
-- table (client_sales_invoices) so recurring billing reuses the Sales engine
-- rather than introducing a second invoicing/GST implementation.
--
-- Additive, backward-compatible, idempotent. Rollback drops only new objects.
-- Money stays integer paise; gst is computed by the existing Sales engine.

-- 1. Traceability columns: every generated invoice links back to its
--    billing_schedule (and thus the originating practice client) + period.
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS billing_schedule_id uuid;
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS billing_period text;
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS source text;  -- e.g. 'billing'

DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'client_sales_invoices_billing_schedule_id_fkey'
      AND table_name = 'client_sales_invoices'
  ) THEN
    ALTER TABLE client_sales_invoices
      ADD CONSTRAINT client_sales_invoices_billing_schedule_id_fkey
      FOREIGN KEY (billing_schedule_id) REFERENCES billing_schedules(id) ON DELETE SET NULL;
  END IF;
END $$;

COMMENT ON COLUMN client_sales_invoices.billing_schedule_id IS
  'Amd v1.1 Batch 3: the billing_schedule that generated this invoice (NULL for manual invoices). Traces to the originating practice client via billing_schedules.client_id.';
COMMENT ON COLUMN client_sales_invoices.billing_period IS
  'Amd v1.1 Batch 3: the period this generated invoice covers (e.g. 2026-06, 2026-Q1, 2026-27, ONCE). Unique per schedule.';

-- 2. DUPLICATE-INVOICE SAFETY (authoritative). At most one invoice per
--    (schedule, period). This is the backstop that makes generation
--    idempotent / replay-safe even under concurrent runs.
CREATE UNIQUE INDEX IF NOT EXISTS uq_client_sales_invoices_billing_run
  ON client_sales_invoices(billing_schedule_id, billing_period)
  WHERE billing_schedule_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_billing_schedule
  ON client_sales_invoices(billing_schedule_id) WHERE billing_schedule_id IS NOT NULL;

-- 3. Guardrail G1 on client_sales_invoices (the real sales table; 074 listed the
--    Doc-5 name 'sales_invoices' which does not exist here). Ensure a permissive
--    firm policy exists (no lockout) + add the restrictive partner-only policy
--    for the internal practice client. get_my_role()/my_internal_client_id()
--    come from migrations 073/074.
ALTER TABLE client_sales_invoices ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "client_sales_invoices_own_firm" ON client_sales_invoices;
CREATE POLICY "client_sales_invoices_own_firm" ON client_sales_invoices
  FOR ALL USING (firm_id = get_my_firm_id()) WITH CHECK (firm_id = get_my_firm_id());

-- client_id::text IS DISTINCT FROM my_internal_client_id()::text: cast both sides
-- for the same type-safety reason documented in migration 074 (uuid helper vs.
-- mixed uuid/text client_id columns). client_sales_invoices.client_id is uuid, so
-- the cast is a no-op here, but it is applied for cross-migration consistency.
DROP POLICY IF EXISTS "client_sales_invoices_internal_partner_only" ON client_sales_invoices;
CREATE POLICY "client_sales_invoices_internal_partner_only" ON client_sales_invoices
  AS RESTRICTIVE FOR ALL
  USING (get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM my_internal_client_id()::text)
  WITH CHECK (get_my_role() = 'Partner' OR client_id::text IS DISTINCT FROM my_internal_client_id()::text);
