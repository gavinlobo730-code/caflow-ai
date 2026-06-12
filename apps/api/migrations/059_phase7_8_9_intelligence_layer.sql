-- Migration: 059_phase7_8_9_intelligence_layer.sql
-- PracticeSync Phase 7/8/9 — Unified Intelligence Layer
-- Agents: Client Lifecycle, Relationship Intelligence, Health Engine, AI Readiness
-- All tables use firm_id for multi-tenancy with RLS.

-- ============================================================
-- SHARED UTILITIES
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$;

CREATE OR REPLACE FUNCTION health_grade_from_score(score int) RETURNS text AS $$
  SELECT CASE
    WHEN score >= 85 THEN 'A'
    WHEN score >= 70 THEN 'B'
    WHEN score >= 55 THEN 'C'
    WHEN score >= 40 THEN 'D'
    ELSE 'F'
  END;
$$ LANGUAGE sql IMMUTABLE;

-- ============================================================
-- AGENT 1 — CLIENT LIFECYCLE
-- ============================================================

-- leads
CREATE TABLE IF NOT EXISTS leads (
  id                   uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id              uuid NOT NULL,
  company_name         text NOT NULL,
  contact_name         text,
  email                text,
  phone                text,
  source               text CHECK (source IN ('referral','website','cold','event','other')),
  stage                text NOT NULL DEFAULT 'Lead' CHECK (stage IN (
                         'Lead','Qualified','Proposal Sent','Proposal Accepted',
                         'Onboarding','Active','Dormant','Renewal Due','Exiting','Exited'
                       )),
  estimated_value_paise bigint DEFAULT 0,
  assigned_to          uuid REFERENCES auth.users(id),
  expected_close_date  date,
  notes                text,
  is_converted         boolean DEFAULT false,
  converted_client_id  uuid,
  created_by           uuid,
  created_at           timestamptz DEFAULT now(),
  updated_at           timestamptz DEFAULT now()
);

ALTER TABLE leads ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON leads
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS leads_firm_id_idx        ON leads (firm_id);
CREATE INDEX IF NOT EXISTS leads_stage_idx          ON leads (stage);
CREATE INDEX IF NOT EXISTS leads_assigned_to_idx    ON leads (assigned_to);

CREATE TRIGGER leads_updated_at
  BEFORE UPDATE ON leads
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- lead_contacts
CREATE TABLE IF NOT EXISTS lead_contacts (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id      uuid NOT NULL,
  lead_id      uuid REFERENCES leads(id) ON DELETE CASCADE,
  name         text NOT NULL,
  email        text,
  phone        text,
  designation  text,
  is_primary   boolean DEFAULT false,
  created_at   timestamptz DEFAULT now(),
  updated_at   timestamptz DEFAULT now()
);

ALTER TABLE lead_contacts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON lead_contacts
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS lead_contacts_firm_id_idx ON lead_contacts (firm_id);
CREATE INDEX IF NOT EXISTS lead_contacts_lead_id_idx ON lead_contacts (lead_id);

CREATE TRIGGER lead_contacts_updated_at
  BEFORE UPDATE ON lead_contacts
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- lead_activities
CREATE TABLE IF NOT EXISTS lead_activities (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        uuid NOT NULL,
  lead_id        uuid REFERENCES leads(id) ON DELETE CASCADE,
  activity_type  text NOT NULL CHECK (activity_type IN ('call','email','meeting','note','follow_up')),
  description    text,
  activity_date  timestamptz DEFAULT now(),
  created_by     uuid,
  created_at     timestamptz DEFAULT now(),
  updated_at     timestamptz DEFAULT now()
);

ALTER TABLE lead_activities ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON lead_activities
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS lead_activities_firm_id_idx ON lead_activities (firm_id);
CREATE INDEX IF NOT EXISTS lead_activities_lead_id_idx ON lead_activities (lead_id);

CREATE TRIGGER lead_activities_updated_at
  BEFORE UPDATE ON lead_activities
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- proposals
CREATE TABLE IF NOT EXISTS proposals (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         uuid NOT NULL,
  lead_id         uuid REFERENCES leads(id),
  client_id       uuid,
  proposal_no     text NOT NULL,
  title           text NOT NULL,
  scope_of_work   text,
  fee_paise       bigint NOT NULL DEFAULT 0,
  validity_days   int DEFAULT 30,
  status          text DEFAULT 'Draft' CHECK (status IN ('Draft','Sent','Accepted','Rejected','Expired')),
  sent_at         timestamptz,
  accepted_at     timestamptz,
  rejected_at     timestamptz,
  created_by      uuid,
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

ALTER TABLE proposals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON proposals
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS proposals_firm_id_idx  ON proposals (firm_id);
CREATE INDEX IF NOT EXISTS proposals_lead_id_idx  ON proposals (lead_id);
CREATE INDEX IF NOT EXISTS proposals_client_id_idx ON proposals (client_id);

CREATE TRIGGER proposals_updated_at
  BEFORE UPDATE ON proposals
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- engagement_letters
CREATE TABLE IF NOT EXISTS engagement_letters (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id             uuid NOT NULL,
  client_id           uuid NOT NULL,
  proposal_id         uuid REFERENCES proposals(id),
  letter_no           text NOT NULL,
  financial_year      text NOT NULL,
  services            jsonb DEFAULT '[]',
  fee_paise           bigint NOT NULL DEFAULT 0,
  signed_by_client    boolean DEFAULT false,
  signed_at           timestamptz,
  status              text DEFAULT 'Draft' CHECK (status IN ('Draft','Sent','Signed','Expired')),
  created_by          uuid,
  created_at          timestamptz DEFAULT now(),
  updated_at          timestamptz DEFAULT now()
);

ALTER TABLE engagement_letters ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON engagement_letters
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS engagement_letters_firm_id_idx    ON engagement_letters (firm_id);
CREATE INDEX IF NOT EXISTS engagement_letters_client_id_idx  ON engagement_letters (client_id);
CREATE INDEX IF NOT EXISTS engagement_letters_proposal_id_idx ON engagement_letters (proposal_id);

CREATE TRIGGER engagement_letters_updated_at
  BEFORE UPDATE ON engagement_letters
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- onboarding_workflows
CREATE TABLE IF NOT EXISTS onboarding_workflows (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         uuid NOT NULL,
  client_id       uuid NOT NULL,
  template_name   text DEFAULT 'Standard',
  status          text DEFAULT 'pending' CHECK (status IN ('pending','in_progress','completed','cancelled')),
  started_at      timestamptz,
  completed_at    timestamptz,
  assigned_to     uuid,
  created_by      uuid,
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

ALTER TABLE onboarding_workflows ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON onboarding_workflows
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS onboarding_workflows_firm_id_idx   ON onboarding_workflows (firm_id);
CREATE INDEX IF NOT EXISTS onboarding_workflows_client_id_idx ON onboarding_workflows (client_id);

CREATE TRIGGER onboarding_workflows_updated_at
  BEFORE UPDATE ON onboarding_workflows
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- onboarding_tasks
CREATE TABLE IF NOT EXISTS onboarding_tasks (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        uuid NOT NULL,
  workflow_id    uuid REFERENCES onboarding_workflows(id) ON DELETE CASCADE,
  task_name      text NOT NULL,
  description    text,
  sort_order     int DEFAULT 0,
  is_required    boolean DEFAULT true,
  status         text DEFAULT 'pending' CHECK (status IN ('pending','in_progress','done','skipped')),
  due_date       date,
  completed_at   timestamptz,
  completed_by   uuid,
  created_at     timestamptz DEFAULT now(),
  updated_at     timestamptz DEFAULT now()
);

ALTER TABLE onboarding_tasks ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON onboarding_tasks
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS onboarding_tasks_firm_id_idx     ON onboarding_tasks (firm_id);
CREATE INDEX IF NOT EXISTS onboarding_tasks_workflow_id_idx ON onboarding_tasks (workflow_id);

CREATE TRIGGER onboarding_tasks_updated_at
  BEFORE UPDATE ON onboarding_tasks
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- renewals
CREATE TABLE IF NOT EXISTS renewals (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         uuid NOT NULL,
  client_id       uuid NOT NULL,
  financial_year  text NOT NULL,
  renewal_date    date NOT NULL,
  fee_paise       bigint DEFAULT 0,
  status          text DEFAULT 'pending' CHECK (status IN ('pending','sent','accepted','rejected','expired')),
  sent_at         timestamptz,
  accepted_at     timestamptz,
  notes           text,
  created_by      uuid,
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

ALTER TABLE renewals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON renewals
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS renewals_firm_id_idx    ON renewals (firm_id);
CREATE INDEX IF NOT EXISTS renewals_client_id_idx  ON renewals (client_id);
CREATE INDEX IF NOT EXISTS renewals_renewal_date_idx ON renewals (renewal_date);

CREATE TRIGGER renewals_updated_at
  BEFORE UPDATE ON renewals
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- client_lifecycle_events
CREATE TABLE IF NOT EXISTS client_lifecycle_events (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id      uuid NOT NULL,
  lead_id      uuid,
  client_id    uuid,
  event_type   text NOT NULL,
  from_stage   text,
  to_stage     text,
  description  text,
  created_by   uuid,
  created_at   timestamptz DEFAULT now()
);

ALTER TABLE client_lifecycle_events ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON client_lifecycle_events
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS client_lifecycle_events_firm_id_idx   ON client_lifecycle_events (firm_id);
CREATE INDEX IF NOT EXISTS client_lifecycle_events_lead_id_idx   ON client_lifecycle_events (lead_id);
CREATE INDEX IF NOT EXISTS client_lifecycle_events_client_id_idx ON client_lifecycle_events (client_id);

-- ============================================================
-- AGENT 2 — RELATIONSHIP INTELLIGENCE
-- ============================================================

-- entities
CREATE TABLE IF NOT EXISTS entities (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id      uuid NOT NULL,
  entity_type  text NOT NULL CHECK (entity_type IN (
                 'Individual','Company','LLP','Partnership','Trust','HUF','Other'
               )),
  full_name    text NOT NULL,
  pan          text,
  gstin        text,
  email        text,
  phone        text,
  address      text,
  notes        text,
  is_active    boolean DEFAULT true,
  created_by   uuid,
  created_at   timestamptz DEFAULT now(),
  updated_at   timestamptz DEFAULT now()
);

-- GSTIN format: 2-digit state code + PAN (10 chars) + 1 entity number + Z + 1 check digit (CGST Act Section 25)
-- PAN format: AAAAA9999A (5 uppercase letters + 4 digits + 1 uppercase letter) (IT Act Section 139A)
ALTER TABLE entities ADD CONSTRAINT entities_pan_unique UNIQUE NULLS NOT DISTINCT (firm_id, pan);

ALTER TABLE entities ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON entities
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS entities_firm_id_idx ON entities (firm_id);
CREATE INDEX IF NOT EXISTS entities_pan_idx     ON entities (pan) WHERE pan IS NOT NULL;
CREATE INDEX IF NOT EXISTS entities_gstin_idx   ON entities (gstin) WHERE gstin IS NOT NULL;

CREATE TRIGGER entities_updated_at
  BEFORE UPDATE ON entities
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- entity_roles
CREATE TABLE IF NOT EXISTS entity_roles (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id            uuid NOT NULL,
  entity_id          uuid REFERENCES entities(id) ON DELETE CASCADE,
  role               text NOT NULL CHECK (role IN (
                       'Director','Shareholder','Partner','Beneficial Owner','Related Party',
                       'Loan Provider','Loan Recipient','Trustee','Beneficiary','Guarantor',
                       'Authorized Signatory'
                     )),
  client_id          uuid NOT NULL,
  effective_from     date,
  effective_to       date,
  ownership_percent  numeric(5,2),
  notes              text,
  created_at         timestamptz DEFAULT now(),
  updated_at         timestamptz DEFAULT now()
);

ALTER TABLE entity_roles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON entity_roles
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS entity_roles_firm_id_idx   ON entity_roles (firm_id);
CREATE INDEX IF NOT EXISTS entity_roles_entity_id_idx ON entity_roles (entity_id);
CREATE INDEX IF NOT EXISTS entity_roles_client_id_idx ON entity_roles (client_id);

CREATE TRIGGER entity_roles_updated_at
  BEFORE UPDATE ON entity_roles
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- entity_relationships
CREATE TABLE IF NOT EXISTS entity_relationships (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id             uuid NOT NULL,
  from_entity_id      uuid REFERENCES entities(id) ON DELETE CASCADE,
  to_entity_id        uuid REFERENCES entities(id) ON DELETE CASCADE,
  relationship_type   text NOT NULL,
  description         text,
  is_active           boolean DEFAULT true,
  created_by          uuid,
  created_at          timestamptz DEFAULT now(),
  updated_at          timestamptz DEFAULT now()
);

ALTER TABLE entity_relationships ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON entity_relationships
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS entity_relationships_firm_id_idx       ON entity_relationships (firm_id);
CREATE INDEX IF NOT EXISTS entity_relationships_from_entity_idx   ON entity_relationships (from_entity_id);
CREATE INDEX IF NOT EXISTS entity_relationships_to_entity_idx     ON entity_relationships (to_entity_id);

CREATE TRIGGER entity_relationships_updated_at
  BEFORE UPDATE ON entity_relationships
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- entity_client_links
CREATE TABLE IF NOT EXISTS entity_client_links (
  id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id             uuid NOT NULL,
  entity_id           uuid REFERENCES entities(id) ON DELETE CASCADE,
  client_id           uuid NOT NULL,
  link_type           text NOT NULL,
  is_primary_contact  boolean DEFAULT false,
  created_at          timestamptz DEFAULT now(),
  updated_at          timestamptz DEFAULT now()
);

ALTER TABLE entity_client_links ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON entity_client_links
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS entity_client_links_firm_id_idx   ON entity_client_links (firm_id);
CREATE INDEX IF NOT EXISTS entity_client_links_entity_id_idx ON entity_client_links (entity_id);
CREATE INDEX IF NOT EXISTS entity_client_links_client_id_idx ON entity_client_links (client_id);

CREATE TRIGGER entity_client_links_updated_at
  BEFORE UPDATE ON entity_client_links
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- entity_addresses
CREATE TABLE IF NOT EXISTS entity_addresses (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        uuid NOT NULL,
  entity_id      uuid REFERENCES entities(id) ON DELETE CASCADE,
  address_type   text DEFAULT 'Registered',
  address_line1  text,
  address_line2  text,
  city           text,
  state          text,
  pincode        text,
  country        text DEFAULT 'India',
  created_at     timestamptz DEFAULT now(),
  updated_at     timestamptz DEFAULT now()
);

ALTER TABLE entity_addresses ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON entity_addresses
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS entity_addresses_firm_id_idx   ON entity_addresses (firm_id);
CREATE INDEX IF NOT EXISTS entity_addresses_entity_id_idx ON entity_addresses (entity_id);

CREATE TRIGGER entity_addresses_updated_at
  BEFORE UPDATE ON entity_addresses
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- entity_documents
CREATE TABLE IF NOT EXISTS entity_documents (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        uuid NOT NULL,
  entity_id      uuid REFERENCES entities(id) ON DELETE CASCADE,
  document_type  text NOT NULL,
  document_no    text,
  file_url       text,
  verified       boolean DEFAULT false,
  expiry_date    date,
  created_at     timestamptz DEFAULT now(),
  updated_at     timestamptz DEFAULT now()
);

ALTER TABLE entity_documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON entity_documents
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS entity_documents_firm_id_idx   ON entity_documents (firm_id);
CREATE INDEX IF NOT EXISTS entity_documents_entity_id_idx ON entity_documents (entity_id);

CREATE TRIGGER entity_documents_updated_at
  BEFORE UPDATE ON entity_documents
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- cross_client_matches
CREATE TABLE IF NOT EXISTS cross_client_matches (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id       uuid NOT NULL,
  entity_id     uuid REFERENCES entities(id),
  client_id_a   uuid NOT NULL,
  client_id_b   uuid NOT NULL,
  match_type    text NOT NULL CHECK (match_type IN ('pan','gstin','name','email')),
  match_value   text,
  confidence    text DEFAULT 'high' CHECK (confidence IN ('high','medium','low')),
  reviewed      boolean DEFAULT false,
  is_confirmed  boolean,
  reviewed_by   uuid,
  reviewed_at   timestamptz,
  created_at    timestamptz DEFAULT now(),
  updated_at    timestamptz DEFAULT now()
);

ALTER TABLE cross_client_matches ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON cross_client_matches
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS cross_client_matches_firm_id_idx    ON cross_client_matches (firm_id);
CREATE INDEX IF NOT EXISTS cross_client_matches_entity_id_idx  ON cross_client_matches (entity_id);
CREATE INDEX IF NOT EXISTS cross_client_matches_client_a_idx   ON cross_client_matches (client_id_a);
CREATE INDEX IF NOT EXISTS cross_client_matches_client_b_idx   ON cross_client_matches (client_id_b);

CREATE TRIGGER cross_client_matches_updated_at
  BEFORE UPDATE ON cross_client_matches
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- AGENT 3 — HEALTH ENGINE
-- ============================================================

-- health_scores
CREATE TABLE IF NOT EXISTS health_scores (
  id                       uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id                  uuid NOT NULL,
  client_id                uuid NOT NULL,
  overall_score            int CHECK (overall_score BETWEEN 0 AND 100),
  compliance_score         int CHECK (compliance_score BETWEEN 0 AND 100),
  accounting_score         int CHECK (accounting_score BETWEEN 0 AND 100),
  documents_score          int CHECK (documents_score BETWEEN 0 AND 100),
  responsiveness_score     int CHECK (responsiveness_score BETWEEN 0 AND 100),
  relationship_risk_score  int CHECK (relationship_risk_score BETWEEN 0 AND 100),
  financial_risk_score     int CHECK (financial_risk_score BETWEEN 0 AND 100),
  engagement_health_score  int CHECK (engagement_health_score BETWEEN 0 AND 100),
  health_grade             text CHECK (health_grade IN ('A','B','C','D','F')),
  is_critical              boolean DEFAULT false,
  is_at_risk               boolean DEFAULT false,
  last_calculated_at       timestamptz DEFAULT now(),
  notes                    text,
  created_at               timestamptz DEFAULT now(),
  updated_at               timestamptz DEFAULT now(),
  UNIQUE (firm_id, client_id)
);

ALTER TABLE health_scores ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON health_scores
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS health_scores_firm_id_idx   ON health_scores (firm_id);
CREATE INDEX IF NOT EXISTS health_scores_client_id_idx ON health_scores (client_id);
CREATE INDEX IF NOT EXISTS health_scores_grade_idx     ON health_scores (health_grade);
CREATE INDEX IF NOT EXISTS health_scores_critical_idx  ON health_scores (is_critical) WHERE is_critical = true;

CREATE TRIGGER health_scores_updated_at
  BEFORE UPDATE ON health_scores
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- health_score_history
CREATE TABLE IF NOT EXISTS health_score_history (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        uuid NOT NULL,
  client_id      uuid NOT NULL,
  overall_score  int,
  health_grade   text,
  recorded_at    timestamptz DEFAULT now(),
  snapshot_data  jsonb,
  created_at     timestamptz DEFAULT now()
);

ALTER TABLE health_score_history ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON health_score_history
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS health_score_history_firm_id_idx   ON health_score_history (firm_id);
CREATE INDEX IF NOT EXISTS health_score_history_client_id_idx ON health_score_history (client_id);
CREATE INDEX IF NOT EXISTS health_score_history_recorded_at_idx ON health_score_history (recorded_at DESC);

-- health_dimension_scores
CREATE TABLE IF NOT EXISTS health_dimension_scores (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        uuid NOT NULL,
  client_id      uuid NOT NULL,
  dimension      text NOT NULL,
  score          int CHECK (score BETWEEN 0 AND 100),
  weight         numeric(4,2) DEFAULT 1.0,
  evidence       jsonb DEFAULT '{}',
  calculated_at  timestamptz DEFAULT now(),
  created_at     timestamptz DEFAULT now(),
  updated_at     timestamptz DEFAULT now()
);

ALTER TABLE health_dimension_scores ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON health_dimension_scores
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS health_dimension_scores_firm_id_idx   ON health_dimension_scores (firm_id);
CREATE INDEX IF NOT EXISTS health_dimension_scores_client_id_idx ON health_dimension_scores (client_id);
CREATE INDEX IF NOT EXISTS health_dimension_scores_dimension_idx ON health_dimension_scores (dimension);

CREATE TRIGGER health_dimension_scores_updated_at
  BEFORE UPDATE ON health_dimension_scores
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- health_overrides
CREATE TABLE IF NOT EXISTS health_overrides (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id         uuid NOT NULL,
  client_id       uuid NOT NULL,
  dimension       text,
  override_score  int CHECK (override_score BETWEEN 0 AND 100),
  reason          text NOT NULL,
  override_by     uuid,
  override_at     timestamptz DEFAULT now(),
  expires_at      timestamptz,
  is_active       boolean DEFAULT true,
  created_at      timestamptz DEFAULT now(),
  updated_at      timestamptz DEFAULT now()
);

ALTER TABLE health_overrides ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON health_overrides
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS health_overrides_firm_id_idx   ON health_overrides (firm_id);
CREATE INDEX IF NOT EXISTS health_overrides_client_id_idx ON health_overrides (client_id);
CREATE INDEX IF NOT EXISTS health_overrides_active_idx    ON health_overrides (is_active) WHERE is_active = true;

CREATE TRIGGER health_overrides_updated_at
  BEFORE UPDATE ON health_overrides
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- health_alerts
CREATE TABLE IF NOT EXISTS health_alerts (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id      uuid NOT NULL,
  client_id    uuid NOT NULL,
  alert_type   text NOT NULL,
  dimension    text,
  message      text NOT NULL,
  severity     text DEFAULT 'warning' CHECK (severity IN ('info','warning','critical')),
  is_resolved  boolean DEFAULT false,
  resolved_by  uuid,
  resolved_at  timestamptz,
  created_at   timestamptz DEFAULT now(),
  updated_at   timestamptz DEFAULT now()
);

ALTER TABLE health_alerts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON health_alerts
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS health_alerts_firm_id_idx    ON health_alerts (firm_id);
CREATE INDEX IF NOT EXISTS health_alerts_client_id_idx  ON health_alerts (client_id);
CREATE INDEX IF NOT EXISTS health_alerts_severity_idx   ON health_alerts (severity);
CREATE INDEX IF NOT EXISTS health_alerts_unresolved_idx ON health_alerts (is_resolved) WHERE is_resolved = false;

CREATE TRIGGER health_alerts_updated_at
  BEFORE UPDATE ON health_alerts
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- ============================================================
-- AGENT 5 — AI READINESS (infrastructure only)
-- ============================================================

-- ai_signals
CREATE TABLE IF NOT EXISTS ai_signals (
  id           uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id      uuid NOT NULL,
  client_id    uuid,
  signal_type  text NOT NULL,
  signal_data  jsonb DEFAULT '{}',
  source       text,
  processed    boolean DEFAULT false,
  created_at   timestamptz DEFAULT now()
);

ALTER TABLE ai_signals ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON ai_signals
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS ai_signals_firm_id_idx    ON ai_signals (firm_id);
CREATE INDEX IF NOT EXISTS ai_signals_client_id_idx  ON ai_signals (client_id);
CREATE INDEX IF NOT EXISTS ai_signals_processed_idx  ON ai_signals (processed) WHERE processed = false;

-- ai_evidence
CREATE TABLE IF NOT EXISTS ai_evidence (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        uuid NOT NULL,
  client_id      uuid,
  signal_id      uuid REFERENCES ai_signals(id),
  evidence_type  text NOT NULL,
  content        jsonb DEFAULT '{}',
  created_at     timestamptz DEFAULT now()
);

ALTER TABLE ai_evidence ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON ai_evidence
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS ai_evidence_firm_id_idx   ON ai_evidence (firm_id);
CREATE INDEX IF NOT EXISTS ai_evidence_client_id_idx ON ai_evidence (client_id);
CREATE INDEX IF NOT EXISTS ai_evidence_signal_id_idx ON ai_evidence (signal_id);

-- ai_trigger_registry
CREATE TABLE IF NOT EXISTS ai_trigger_registry (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id        uuid NOT NULL,
  trigger_name   text NOT NULL,
  trigger_event  text NOT NULL,
  conditions     jsonb DEFAULT '{}',
  is_active      boolean DEFAULT true,
  created_at     timestamptz DEFAULT now(),
  updated_at     timestamptz DEFAULT now()
);

ALTER TABLE ai_trigger_registry ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON ai_trigger_registry
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS ai_trigger_registry_firm_id_idx ON ai_trigger_registry (firm_id);
CREATE INDEX IF NOT EXISTS ai_trigger_registry_active_idx  ON ai_trigger_registry (is_active) WHERE is_active = true;

CREATE TRIGGER ai_trigger_registry_updated_at
  BEFORE UPDATE ON ai_trigger_registry
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- client_profiles
CREATE TABLE IF NOT EXISTS client_profiles (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id          uuid NOT NULL,
  client_id        uuid NOT NULL,
  profile_data     jsonb DEFAULT '{}',
  tags             text[] DEFAULT '{}',
  segment          text,
  last_updated_at  timestamptz DEFAULT now(),
  created_at       timestamptz DEFAULT now(),
  updated_at       timestamptz DEFAULT now(),
  UNIQUE (firm_id, client_id)
);

ALTER TABLE client_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON client_profiles
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS client_profiles_firm_id_idx   ON client_profiles (firm_id);
CREATE INDEX IF NOT EXISTS client_profiles_client_id_idx ON client_profiles (client_id);
CREATE INDEX IF NOT EXISTS client_profiles_tags_idx      ON client_profiles USING GIN (tags);

CREATE TRIGGER client_profiles_updated_at
  BEFORE UPDATE ON client_profiles
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

-- firm_profiles
CREATE TABLE IF NOT EXISTS firm_profiles (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  firm_id          uuid NOT NULL,
  profile_data     jsonb DEFAULT '{}',
  settings         jsonb DEFAULT '{}',
  last_updated_at  timestamptz DEFAULT now(),
  created_at       timestamptz DEFAULT now(),
  updated_at       timestamptz DEFAULT now(),
  UNIQUE (firm_id)
);

ALTER TABLE firm_profiles ENABLE ROW LEVEL SECURITY;
CREATE POLICY "firm_isolation" ON firm_profiles
  USING (firm_id::text = auth.jwt()->>'firm_id');

CREATE INDEX IF NOT EXISTS firm_profiles_firm_id_idx ON firm_profiles (firm_id);

CREATE TRIGGER firm_profiles_updated_at
  BEFORE UPDATE ON firm_profiles
  FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
