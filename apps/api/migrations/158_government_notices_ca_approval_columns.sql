-- ============================================================================
-- 158: government_notices CA-approval columns (R2.8 fix-phase; audit F19).
--
-- Migration 052 created public.government_notices without ca_approved /
-- ca_approved_by / ca_approved_at, but routers/document_intelligence_v2.py
-- has always read and written all three:
--   * POST /notices/extract inserts "ca_approved": False on every new notice
--     (the honest-extraction success path this R2.8 milestone's own tests
--     assert works end-to-end).
--   * POST /notices/{id}/approve updates ca_approved / ca_approved_by /
--     ca_approved_at as the required human-in-the-loop approval step.
--
-- Against real Postgres/PostgREST (SUPABASE_URL configured, _USE_MOCK=False)
-- both inserts/updates reference columns absent from the schema cache and
-- are rejected outright, so even a genuine, non-fabricated Groq extraction
-- was never persisted in production. This is additive-only and does not
-- touch any other migration file (same repair pattern as 155/157).
-- ============================================================================

ALTER TABLE public.government_notices
  ADD COLUMN IF NOT EXISTS ca_approved    BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS ca_approved_by UUID,
  ADD COLUMN IF NOT EXISTS ca_approved_at TIMESTAMPTZ;
