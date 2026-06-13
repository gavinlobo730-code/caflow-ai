-- Migration 061: Add missing columns for Phase 7/8/9 routers
-- Fixes column gaps between router code and migration 059 schema.

-- entities: router model includes date_of_birth; add the column so INSERT doesn't fail
ALTER TABLE entities ADD COLUMN IF NOT EXISTS date_of_birth date;

-- entity_relationships: RelationshipIn model includes effective_from/effective_to
ALTER TABLE entity_relationships ADD COLUMN IF NOT EXISTS effective_from date;
ALTER TABLE entity_relationships ADD COLUMN IF NOT EXISTS effective_to date;

-- cross_client_matches: column is is_confirmed; rename the alias used in older migration
-- (column already named is_confirmed in 059 — this is a no-op guard)
ALTER TABLE cross_client_matches ADD COLUMN IF NOT EXISTS notes text;

-- Ensure service-role key used by backend can access all Phase 7 tables
-- (service_role bypasses RLS by default — these grants cover anon/authenticated clients)
GRANT SELECT, INSERT, UPDATE, DELETE ON leads TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON proposals TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_workflows TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON onboarding_tasks TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON renewals TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON client_lifecycle_events TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON entities TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON entity_roles TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON entity_relationships TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON cross_client_matches TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON health_scores TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON health_score_history TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON health_overrides TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON health_alerts TO authenticated;
