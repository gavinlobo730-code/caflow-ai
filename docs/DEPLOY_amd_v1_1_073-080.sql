-- ============================================================================
-- PracticeSync Amendment v1.1 — consolidated migrations 073–080 (FORWARD)
-- Apply in this exact order. Idempotent (safe to re-run). Run as a single
-- script in the Supabase SQL editor (or psql). Apply 080 BEFORE provisioning.
-- Rollback files (per migration) live in apps/api/migrations/*_rollback.sql.
-- ============================================================================

-- ====================== 073_revenue_ops_foundation.sql ======================
-- PracticeSync AI — Migration 073: Revenue Operations & Knowledge Base Foundation
-- Amendment v1.1 (Phase 10B) — BATCH 1: SCHEMA + SECURITY FOUNDATION ONLY.
--
-- Scope: additive schema, constraints, indexes, foreign keys, RLS policies,
-- a partner-role helper, the clients_external exclusion view, and an idempotent
-- internal-client provisioning FUNCTION (a foundation invoked later in Batch 2).
-- NO business logic, services, APIs, UI, or workflows are introduced here.
--
-- Backward-compatibility (hard constraint): every new column is nullable or
-- defaulted (is_internal default false, cost/billable rates null), every new
-- table is independent, and no existing column, table, route, or workflow is
-- changed. Applying this migration cannot alter existing behaviour.
--
-- Money: all monetary columns are BIGINT integer paise. Never float.
--        (gst_rate is a percentage rate, not a rupee amount.)
-- Idempotent — safe to run multiple times.
-- Rollback: 073_revenue_ops_foundation_rollback.sql (drops only new objects).

-- ============================================================================
-- 1. COLUMN ADDITIONS (existing tables) — all nullable/defaulted
-- ============================================================================
ALTER TABLE clients      ADD COLUMN IF NOT EXISTS is_internal BOOLEAN NOT NULL DEFAULT false;
ALTER TABLE firms        ADD COLUMN IF NOT EXISTS internal_client_id UUID;
ALTER TABLE users        ADD COLUMN IF NOT EXISTS cost_rate_paise BIGINT;
ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS billable_rate_paise BIGINT;

-- firms.internal_client_id -> clients(id) (guarded; ON DELETE SET NULL keeps firm intact)
DO $$ BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.table_constraints
    WHERE constraint_name = 'firms_internal_client_id_fkey' AND table_name = 'firms'
  ) THEN
    ALTER TABLE firms
      ADD CONSTRAINT firms_internal_client_id_fkey
      FOREIGN KEY (internal_client_id) REFERENCES clients(id) ON DELETE SET NULL;
  END IF;
END $$;

COMMENT ON COLUMN clients.is_internal IS
  'Amd v1.1 FR-FIC-01/02: true only for the firm-as-internal-client row; excluded from all client-population surfaces (use clients_external).';
COMMENT ON COLUMN firms.internal_client_id IS
  'Amd v1.1 FR-FIC-01: points to this firm''s single is_internal=true client row (set by provision_internal_client).';
COMMENT ON COLUMN users.cost_rate_paise IS
  'Amd v1.1: staff cost rate in integer paise for realization (Partner-visible). NULL = unset.';
COMMENT ON COLUMN time_entries.billable_rate_paise IS
  'Amd v1.1 FR-REV-07: optional billable rate in integer paise. Coexists with legacy hourly_rate_paise (bridge documented in REVENUE_OPS_BRIDGE.md).';

-- ============================================================================
-- 2. NEW TABLE — billing_schedules (Amd v1.1 §4.2) — Partner-only (fee economics)
-- ============================================================================
CREATE TABLE IF NOT EXISTS billing_schedules (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id       UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id     UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,  -- the practice client billed
  arrangement   TEXT NOT NULL CHECK (arrangement IN ('retainer','one_time','package')),
  service_id    UUID,                          -- -> service_catalogue (not yet in schema): nullable, no FK (bridge)
  amount_paise  BIGINT NOT NULL DEFAULT 0,     -- integer paise
  gst_rate      NUMERIC(5,2) NOT NULL DEFAULT 18.0,  -- percentage rate, not money
  cadence       TEXT NOT NULL CHECK (cadence IN ('monthly','quarterly','annual','one_time')),
  next_run_date DATE,
  is_active     BOOLEAN NOT NULL DEFAULT true,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by    UUID
);
CREATE INDEX IF NOT EXISTS idx_billing_schedules_firm_next_run
  ON billing_schedules(firm_id, next_run_date) WHERE is_active;
CREATE INDEX IF NOT EXISTS idx_billing_schedules_firm_client
  ON billing_schedules(firm_id, client_id);

-- ============================================================================
-- 3. NEW TABLE — client_firm_customer_links (Amd v1.1 §4.3, Guardrail G3) — Partner-only
--    Maps a practice client to exactly ONE customer row in the internal client's books.
-- ============================================================================
CREATE TABLE IF NOT EXISTS client_firm_customer_links (
  id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id              UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id            UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,    -- practice client
  internal_customer_id UUID NOT NULL REFERENCES customers(id) ON DELETE CASCADE,  -- customer in internal client's books
  created_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by           UUID,
  UNIQUE (firm_id, client_id)               -- G3: one link per practice client (no duplicate entity)
);
CREATE INDEX IF NOT EXISTS idx_cfcl_firm_customer
  ON client_firm_customer_links(firm_id, internal_customer_id);

-- ============================================================================
-- 4. NEW TABLES — Knowledge Base (Amd v1.1 §4.4) — firm-scoped
-- ============================================================================
CREATE TABLE IF NOT EXISTS knowledge_articles (
  id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  scope           TEXT NOT NULL CHECK (scope IN ('firm','department','client')),
  department      TEXT,
  client_id       UUID REFERENCES clients(id) ON DELETE CASCADE,  -- required when scope='client' (enforced in Batch 6)
  title           TEXT NOT NULL,
  current_version INTEGER NOT NULL DEFAULT 1,
  tags            TEXT[] NOT NULL DEFAULT '{}',
  is_archived     BOOLEAN NOT NULL DEFAULT false,
  created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  created_by      UUID
);
CREATE INDEX IF NOT EXISTS idx_knowledge_articles_firm_scope  ON knowledge_articles(firm_id, scope);
CREATE INDEX IF NOT EXISTS idx_knowledge_articles_firm_client ON knowledge_articles(firm_id, client_id);
CREATE INDEX IF NOT EXISTS idx_knowledge_articles_title_fts
  ON knowledge_articles USING GIN (to_tsvector('english', coalesce(title, '')));
CREATE INDEX IF NOT EXISTS idx_knowledge_articles_tags ON knowledge_articles USING GIN (tags);

CREATE TABLE IF NOT EXISTS knowledge_article_versions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id     UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  article_id  UUID NOT NULL REFERENCES knowledge_articles(id) ON DELETE CASCADE,
  version     INTEGER NOT NULL,
  content     TEXT NOT NULL DEFAULT '',
  changed_by  UUID,
  changed_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  UNIQUE (article_id, version)
);
CREATE INDEX IF NOT EXISTS idx_kav_firm ON knowledge_article_versions(firm_id);
CREATE INDEX IF NOT EXISTS idx_kav_content_fts
  ON knowledge_article_versions USING GIN (to_tsvector('english', coalesce(content, '')));

CREATE TABLE IF NOT EXISTS client_instructions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id     UUID NOT NULL REFERENCES firms(id) ON DELETE CASCADE,
  client_id   UUID NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
  title       TEXT NOT NULL,
  body        TEXT NOT NULL DEFAULT '',
  is_pinned   BOOLEAN NOT NULL DEFAULT false,
  created_by  UUID,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_client_instructions_firm_client ON client_instructions(firm_id, client_id);

-- ============================================================================
-- 5. ROLE HELPER — get_my_role() (Partner = Owner-equivalent per approved role mapping)
--    SECURITY DEFINER so it reads users.role regardless of the caller's RLS.
-- ============================================================================
CREATE OR REPLACE FUNCTION get_my_role()
RETURNS TEXT AS $$
  SELECT role FROM users WHERE auth_user_id = auth.uid() LIMIT 1;
$$ LANGUAGE SQL SECURITY DEFINER STABLE;

-- ============================================================================
-- 6. RLS — enable + policies (firm isolation; Partner-only on fee-economics tables)
-- ============================================================================
ALTER TABLE billing_schedules          ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_firm_customer_links ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_articles         ENABLE ROW LEVEL SECURITY;
ALTER TABLE knowledge_article_versions ENABLE ROW LEVEL SECURITY;
ALTER TABLE client_instructions        ENABLE ROW LEVEL SECURITY;

-- Partner-only (Guardrail G1 foundation): expose fee economics to Owner/Partner only.
DROP POLICY IF EXISTS "billing_schedules_partner_only" ON billing_schedules;
CREATE POLICY "billing_schedules_partner_only" ON billing_schedules
  FOR ALL USING (firm_id = get_my_firm_id() AND get_my_role() = 'Partner')
  WITH CHECK (firm_id = get_my_firm_id() AND get_my_role() = 'Partner');

DROP POLICY IF EXISTS "client_firm_customer_links_partner_only" ON client_firm_customer_links;
CREATE POLICY "client_firm_customer_links_partner_only" ON client_firm_customer_links
  FOR ALL USING (firm_id = get_my_firm_id() AND get_my_role() = 'Partner')
  WITH CHECK (firm_id = get_my_firm_id() AND get_my_role() = 'Partner');

-- Knowledge Base: firm isolation (client-assignment gating for client-scoped
-- rows is layered in Batch 6 alongside the KB service).
DROP POLICY IF EXISTS "knowledge_articles_own_firm" ON knowledge_articles;
CREATE POLICY "knowledge_articles_own_firm" ON knowledge_articles
  FOR ALL USING (firm_id = get_my_firm_id()) WITH CHECK (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "knowledge_article_versions_own_firm" ON knowledge_article_versions;
CREATE POLICY "knowledge_article_versions_own_firm" ON knowledge_article_versions
  FOR ALL USING (firm_id = get_my_firm_id()) WITH CHECK (firm_id = get_my_firm_id());

DROP POLICY IF EXISTS "client_instructions_own_firm" ON client_instructions;
CREATE POLICY "client_instructions_own_firm" ON client_instructions
  FOR ALL USING (firm_id = get_my_firm_id()) WITH CHECK (firm_id = get_my_firm_id());

-- ============================================================================
-- 7. GRANTS (RLS still applies to authenticated; service_role bypasses RLS)
-- ============================================================================
GRANT SELECT, INSERT, UPDATE, DELETE ON
  billing_schedules, client_firm_customer_links,
  knowledge_articles, knowledge_article_versions, client_instructions
  TO authenticated;
GRANT ALL ON
  billing_schedules, client_firm_customer_links,
  knowledge_articles, knowledge_article_versions, client_instructions
  TO service_role;

-- ============================================================================
-- 8. VIEW — clients_external (Guardrail G2 single source for client-population surfaces)
--    security_invoker => the caller's RLS on clients is enforced through the view.
-- ============================================================================
CREATE OR REPLACE VIEW clients_external
WITH (security_invoker = true) AS
  SELECT * FROM clients WHERE is_internal = false;
GRANT SELECT ON clients_external TO authenticated;
GRANT SELECT ON clients_external TO anon;
COMMENT ON VIEW clients_external IS
  'Amd v1.1 Guardrail G2: the single predicate (is_internal=false) feeding client counts, Clients list, Health triage, lifecycle dashboards, and client-facing Deadlines.';

-- ============================================================================
-- 9. PROVISIONING FOUNDATION — idempotent internal-client provisioner.
--    Created here; INVOKED in Batch 2 with real firm PAN/entity_type. Not run now
--    (clients.pan is NOT NULL + regex-validated, a business input for Batch 2).
-- ============================================================================
CREATE OR REPLACE FUNCTION provision_internal_client(
  p_firm_id     UUID,
  p_legal_name  TEXT,
  p_entity_type TEXT,
  p_pan         TEXT,
  p_gstin       TEXT DEFAULT NULL
) RETURNS UUID AS $$
DECLARE
  v_existing UUID;
  v_new      UUID;
BEGIN
  SELECT internal_client_id INTO v_existing FROM firms WHERE id = p_firm_id;
  IF v_existing IS NOT NULL AND EXISTS (
       SELECT 1 FROM clients WHERE id = v_existing AND is_internal
     ) THEN
    RETURN v_existing;  -- idempotent: already provisioned
  END IF;

  INSERT INTO clients (firm_id, client_name, legal_name, entity_type, pan, gstin, is_internal, status)
  VALUES (p_firm_id, p_legal_name, p_legal_name, p_entity_type, p_pan, p_gstin, true, 'active')
  RETURNING id INTO v_new;

  UPDATE firms SET internal_client_id = v_new WHERE id = p_firm_id;
  RETURN v_new;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

COMMENT ON FUNCTION provision_internal_client(UUID, TEXT, TEXT, TEXT, TEXT) IS
  'Amd v1.1 foundation: idempotently create the firm-as-internal-client row and link firms.internal_client_id. Invoked by Batch 2 (provisioning + guardrails) with real firm details.';

-- ====================== 074_internal_client_rls_guardrails.sql ======================
-- PracticeSync AI — Migration 074: Internal-Client RLS Guardrails (G1 defence-in-depth)
-- Amendment v1.1 (Phase 10B) — BATCH 2.
--
-- The application backend connects with the Supabase SERVICE_ROLE key, which
-- BYPASSES RLS; G1/G2 are therefore enforced primarily in the Python API/repo
-- layer. These RESTRICTIVE policies are DEFENCE-IN-DEPTH for any direct
-- (non-service-role / PostgREST / anon+JWT) access to the database.
--
-- Effect: non-Partner users cannot see or write the internal practice client's
-- row or its financial rows. RESTRICTIVE policies AND with the existing
-- permissive firm-isolation policies (they only ever remove access, never add).
-- "Partner" is the Owner-equivalent role per the approved mapping.
--
-- Additive & idempotent. Rollback: 074_internal_client_rls_guardrails_rollback.sql.

-- Memoised lookup of the caller's firm internal client id (SECURITY DEFINER so
-- it can read firms regardless of the caller's own RLS).
CREATE OR REPLACE FUNCTION my_internal_client_id()
RETURNS uuid AS $$
  SELECT internal_client_id FROM firms WHERE id = get_my_firm_id();
$$ LANGUAGE sql SECURITY DEFINER STABLE;

-- ── clients: hide the internal row from non-Partners ─────────────────────────
DROP POLICY IF EXISTS "clients_internal_partner_only" ON clients;
CREATE POLICY "clients_internal_partner_only" ON clients
  AS RESTRICTIVE FOR ALL
  USING (get_my_role() = 'Partner' OR NOT is_internal)
  WITH CHECK (get_my_role() = 'Partner' OR NOT is_internal);

-- ── financial / client-scoped tables: hide internal-client rows from non-Partners ─
-- Applied to every listed table that exists AND has a client_id column. Uses
-- IS DISTINCT FROM so a NULL internal_client_id (unprovisioned firm) never hides
-- ordinary client rows.
DO $$
DECLARE
  t    text;
  tbls text[] := ARRAY[
    'journal_entries','ledger_balances',
    'sales_invoices','receipts','credit_notes',
    'purchase_bills','purchase_payments',
    'customers','vendors',
    'bank_accounts','bank_transactions','bank_statements','bank_reconciliations',
    'gstr1_returns','gstr3b_returns','gstr2a_records','gstr2b_uploads','gst_challans',
    'tds_returns','tds_deductions','tds_challans','tds_certificates',
    'fixed_assets','loans','fixed_deposits',
    'advance_tax_payments','compliance_records','compliance_tasks',
    'year_end_engagements',
    'payroll_employees','payroll_runs','salary_structures','attendance','leave_balances',
    -- client-scoped read surfaces (Batch 2.1 defence-in-depth)
    'client_timeline_events','documents','document_extractions','document_requests',
    'ai_insights','government_notices','it_notices','tax_notices',
    'billing_schedules','client_firm_customer_links','client_instructions'
  ];
BEGIN
  FOREACH t IN ARRAY tbls LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema='public' AND table_name=t)
       AND EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_schema='public' AND table_name=t AND column_name='client_id') THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I',
                     t || '_internal_partner_only', t);
      EXECUTE format(
        'CREATE POLICY %I ON public.%I AS RESTRICTIVE FOR ALL '
        || 'USING (get_my_role() = ''Partner'' OR client_id IS DISTINCT FROM my_internal_client_id()) '
        || 'WITH CHECK (get_my_role() = ''Partner'' OR client_id IS DISTINCT FROM my_internal_client_id())',
        t || '_internal_partner_only', t);
    END IF;
  END LOOP;
END $$;

-- ====================== 075_billing_traceability.sql ======================
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

DROP POLICY IF EXISTS "client_sales_invoices_internal_partner_only" ON client_sales_invoices;
CREATE POLICY "client_sales_invoices_internal_partner_only" ON client_sales_invoices
  AS RESTRICTIVE FOR ALL
  USING (get_my_role() = 'Partner' OR client_id IS DISTINCT FROM my_internal_client_id())
  WITH CHECK (get_my_role() = 'Partner' OR client_id IS DISTINCT FROM my_internal_client_id());

-- ====================== 076_invoice_journal_link.sql ======================
-- PracticeSync AI — Migration 076: Invoice→Journal link (Batch 3.1 hardening)
-- Amendment v1.1 (Phase 10B).
--
-- Persists the posted journal on the sales invoice so an "issued-but-unposted"
-- invoice is deterministically detectable (status='issued' AND journal_entry_id
-- IS NULL) and remediable. Backward-compatible, additive, idempotent.

ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS journal_entry_id uuid;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='journal_entries')
     AND NOT EXISTS (
       SELECT 1 FROM information_schema.table_constraints
       WHERE constraint_name = 'client_sales_invoices_journal_entry_id_fkey'
         AND table_name = 'client_sales_invoices'
     ) THEN
    ALTER TABLE client_sales_invoices
      ADD CONSTRAINT client_sales_invoices_journal_entry_id_fkey
      FOREIGN KEY (journal_entry_id) REFERENCES journal_entries(id) ON DELETE SET NULL;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_unposted
  ON client_sales_invoices(firm_id) WHERE status = 'issued' AND journal_entry_id IS NULL;

COMMENT ON COLUMN client_sales_invoices.journal_entry_id IS
  'Batch 3.1: the posted journal entry for this issued invoice. NULL on a draft, or on a (legacy) issued-but-unposted invoice pending remediation.';

-- ====================== 077_collections_ar.sql ======================
-- PracticeSync AI — Migration 077: Collections & AR (Batch 4)
-- Amendment v1.1 (Phase 10B) — Revenue Operations collections.
--
-- Additive, backward-compatible, idempotent. Money stays integer paise.
--
-- Per the approved design:
--  * Overdue is DERIVED + denormalised (no status mutation). Payment status
--    (draft/issued/partially_paid/paid/cancelled) is preserved; collections
--    metadata is maintained by a daily sweep.
--  * Aging is DUE-DATE based; due_date else invoice_date + credit_days.
--  * TDS deducted by clients on firm fees is captured on the existing receipt
--    (tds_paise) — settlement value = amount_paise + tds_paise.

-- 1. Collections metadata on the sales invoice (derived; non-destructive)
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS is_overdue       boolean NOT NULL DEFAULT false;
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS days_overdue     integer NOT NULL DEFAULT 0;
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS aging_bucket     text;            -- not_due | 0-30 | 31-60 | 61-90 | 90+
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS last_reminded_at timestamptz;
ALTER TABLE client_sales_invoices ADD COLUMN IF NOT EXISTS reminder_count   integer NOT NULL DEFAULT 0;

COMMENT ON COLUMN client_sales_invoices.is_overdue IS
  'Batch 4: derived (due_date < today AND outstanding > 0). Payment status is never mutated to overdue.';
COMMENT ON COLUMN client_sales_invoices.aging_bucket IS
  'Batch 4 (due-date based): not_due | 0-30 | 31-60 | 61-90 | 90+.';

-- 2. TDS deducted by the client on the firm's fees, captured on the receipt.
ALTER TABLE receipts ADD COLUMN IF NOT EXISTS tds_paise bigint NOT NULL DEFAULT 0;
COMMENT ON COLUMN receipts.tds_paise IS
  'Batch 4: TDS deducted by the client on the firm fee (IT Act §194J). Settlement = amount_paise + tds_paise. Posts Dr TDS Receivable.';

-- 3. Index for the overdue sweep + dashboard (firm-scoped, open receivables only).
CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_open
  ON client_sales_invoices(firm_id, due_date)
  WHERE status IN ('issued','partially_paid');
CREATE INDEX IF NOT EXISTS idx_client_sales_invoices_overdue_flag
  ON client_sales_invoices(firm_id) WHERE is_overdue;

-- ====================== 078_billable_capture.sql ======================
-- PracticeSync AI — Migration 078: Billable / billed capture (Batch 5)
-- Amendment v1.1 (Phase 10B) — DATA-CAPTURE ONLY (no analytics).
--
-- Reuses Batch-1 columns (time_entries.is_billable, time_entries.billable_rate_paise,
-- users.cost_rate_paise). Adds the system-controlled billed linkage so future
-- billing workflows can rely on it without reconciliation:
--   * billed_invoice_id is the AUTHORITATIVE linkage.
--   * is_billed is a GENERATED column derived from billed_invoice_id — it cannot
--     be set manually (Postgres rejects writes to GENERATED ALWAYS columns), so it
--     is system-controlled by construction and always consistent.
-- Additive, backward-compatible, idempotent.

ALTER TABLE time_entries ADD COLUMN IF NOT EXISTS billed_invoice_id uuid;

DO $$ BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.tables
             WHERE table_schema='public' AND table_name='client_sales_invoices')
     AND NOT EXISTS (
       SELECT 1 FROM information_schema.table_constraints
       WHERE constraint_name='time_entries_billed_invoice_id_fkey' AND table_name='time_entries'
     ) THEN
    ALTER TABLE time_entries
      ADD CONSTRAINT time_entries_billed_invoice_id_fkey
      FOREIGN KEY (billed_invoice_id) REFERENCES client_sales_invoices(id) ON DELETE SET NULL;
  END IF;
END $$;

-- System-controlled, derived, non-editable.
ALTER TABLE time_entries
  ADD COLUMN IF NOT EXISTS is_billed boolean
  GENERATED ALWAYS AS (billed_invoice_id IS NOT NULL) STORED;

-- Unbilled-work query: billable AND not yet billed.
CREATE INDEX IF NOT EXISTS idx_time_entries_unbilled
  ON time_entries(firm_id, client_id)
  WHERE is_billable AND billed_invoice_id IS NULL;

COMMENT ON COLUMN time_entries.billed_invoice_id IS
  'Batch 5: authoritative billed linkage (the sales invoice that billed this time). Set by the system; future time-based billing relies on this without reconciliation.';
COMMENT ON COLUMN time_entries.is_billed IS
  'Batch 5: GENERATED from billed_invoice_id (system-controlled; cannot be edited manually).';

-- ====================== 079_knowledge_rls.sql ======================
-- PracticeSync AI — Migration 079: Knowledge Base assignment-gated RLS (Batch 6)
-- Amendment v1.1 (Phase 10B). Additive, idempotent. NO new tables (the KB tables
-- were created in 073). Refines the firm-scoped RLS to assignment-gating:
--   * Partner/Manager  -> firm-wide.
--   * Executive/Reviewer -> only their assigned clients (user_client_assignments).
--   * Internal practice client KB -> Partner-only (G1).
-- Backend uses the service-role key (RLS bypassed) so the API/repository layer is
-- the PRIMARY control; these RESTRICTIVE policies are defense-in-depth.

-- Resolve the caller's internal users.id (for assignment checks).
CREATE OR REPLACE FUNCTION get_my_user_id()
RETURNS uuid AS $$
  SELECT id FROM users WHERE auth_user_id = auth.uid() LIMIT 1;
$$ LANGUAGE sql SECURITY DEFINER STABLE;

-- ── knowledge_articles: assignment-gate client-scoped rows ───────────────────
DROP POLICY IF EXISTS "knowledge_articles_assignment" ON knowledge_articles;
CREATE POLICY "knowledge_articles_assignment" ON knowledge_articles
  AS RESTRICTIVE FOR ALL
  USING (
    get_my_role() IN ('Partner','Manager')
    OR client_id IS NULL                                   -- firm/department scope: all staff
    OR EXISTS (SELECT 1 FROM user_client_assignments a
               WHERE a.user_id = get_my_user_id() AND a.client_id = knowledge_articles.client_id)
  )
  WITH CHECK (
    get_my_role() IN ('Partner','Manager')
    OR client_id IS NULL
    OR EXISTS (SELECT 1 FROM user_client_assignments a
               WHERE a.user_id = get_my_user_id() AND a.client_id = knowledge_articles.client_id)
  );

-- ── knowledge_articles: internal practice client -> Partner-only (G1) ────────
DROP POLICY IF EXISTS "knowledge_articles_internal_partner_only" ON knowledge_articles;
CREATE POLICY "knowledge_articles_internal_partner_only" ON knowledge_articles
  AS RESTRICTIVE FOR ALL
  USING (get_my_role() = 'Partner' OR client_id IS DISTINCT FROM my_internal_client_id())
  WITH CHECK (get_my_role() = 'Partner' OR client_id IS DISTINCT FROM my_internal_client_id());

-- ── client_instructions: assignment-gate (always client-scoped) ──────────────
-- (internal-client partner-only already added for client_instructions in 074)
DROP POLICY IF EXISTS "client_instructions_assignment" ON client_instructions;
CREATE POLICY "client_instructions_assignment" ON client_instructions
  AS RESTRICTIVE FOR ALL
  USING (
    get_my_role() IN ('Partner','Manager')
    OR EXISTS (SELECT 1 FROM user_client_assignments a
               WHERE a.user_id = get_my_user_id() AND a.client_id = client_instructions.client_id)
  )
  WITH CHECK (
    get_my_role() IN ('Partner','Manager')
    OR EXISTS (SELECT 1 FROM user_client_assignments a
               WHERE a.user_id = get_my_user_id() AND a.client_id = client_instructions.client_id)
  );

-- ====================== 080_one_internal_client_per_firm.sql ======================
-- PracticeSync AI — Migration 080: enforce one internal client per firm (Audit fix)
-- Amendment v1.1. Additive, idempotent. Closes the concurrency gap where two
-- simultaneous provisioning calls could create duplicate is_internal=true clients
-- (provision() check-then-insert is not atomic on its own).
--
-- A partial UNIQUE index guarantees at most one internal practice client per firm
-- at the database level. Apply alongside 073–079 BEFORE provisioning runs.

CREATE UNIQUE INDEX IF NOT EXISTS uq_clients_one_internal_per_firm
  ON clients(firm_id) WHERE is_internal;
