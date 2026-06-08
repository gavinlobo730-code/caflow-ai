-- Migration 043: Add category column to ai_insights for service-layer mapping.
-- Additive only — no existing data is modified.

ALTER TABLE ai_insights ADD COLUMN IF NOT EXISTS category TEXT;
CREATE INDEX IF NOT EXISTS idx_ai_insights_category ON ai_insights(firm_id, category) WHERE deleted_at IS NULL;
