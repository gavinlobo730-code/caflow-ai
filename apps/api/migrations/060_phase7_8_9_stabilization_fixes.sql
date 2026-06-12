-- Migration 060: Stabilization fixes for Phase 7/8/9
-- Adds missing columns required by the lifecycle/relationship/health routers.

-- leads: add converted_at timestamp
ALTER TABLE leads ADD COLUMN IF NOT EXISTS converted_at timestamptz;

-- proposals: lifecycle router uses total_value_paise, description, valid_until, notes
-- Map to canonical schema (fee_paise, scope_of_work) + add missing columns
ALTER TABLE proposals ADD COLUMN IF NOT EXISTS valid_until date;
ALTER TABLE proposals ADD COLUMN IF NOT EXISTS description text;
ALTER TABLE proposals ADD COLUMN IF NOT EXISTS total_value_paise bigint DEFAULT 0;
ALTER TABLE proposals ADD COLUMN IF NOT EXISTS notes text;

-- entity_roles: ensure notes column exists
ALTER TABLE entity_roles ADD COLUMN IF NOT EXISTS notes text;

-- health_scores: ensure client_name column exists (used by recalculate-all)
ALTER TABLE health_scores ADD COLUMN IF NOT EXISTS client_name text;

-- Grant access to authenticated users on new tables
GRANT SELECT, INSERT, UPDATE, DELETE ON leads TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON lead_contacts TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON lead_activities TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON proposals TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON engagement_letters TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_workflows TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_tasks TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON renewals TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON client_lifecycle_events TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON entities TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON entity_roles TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON entity_relationships TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON entity_client_links TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON entity_addresses TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON entity_documents TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON cross_client_matches TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON health_scores TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON health_score_history TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON health_dimension_scores TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON health_overrides TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON health_alerts TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_signals TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_evidence TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_trigger_registry TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON client_profiles TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON firm_profiles TO authenticated;
