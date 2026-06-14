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
