-- 169 — fix health_scores/health_score_history schema drift (ADDITIVE ONLY).
--
-- Migration 059 created health_scores/health_score_history for the original
-- Phase 7-8-9 "Intelligence Layer" A-F letter-grade model. routers/health.py was
-- later rewritten to the Product Bible Chapter 16 7-dimension weighted model,
-- but no migration ever followed to match — the router has been writing (and
-- selecting) columns that do not exist on the real table ever since:
--   compliance_health_score, accounting_quality_score, work_progress_score,
--   document_health_score, ai_risk_signals_score, open_notices_score,
--   client_responsiveness_score, dimensions, grade, trend, hard_override,
--   hard_override_reason.
-- Confirmed directly against a freshly-migrated real Postgres 16 instance
-- (`\d health_scores`): none of the above columns exist. Every
-- POST /api/health/scores/{id}/calculate and POST /api/health/recalculate-all
-- call fails against a live (non-mock) deployment — this is the backend for a
-- full top-level "Health" workspace reachable from the sidebar for nearly every
-- role, so this has been a completely broken, universally-visible feature in
-- any real deployment. The router's own defensive insert/update fallback chain
-- (removed in the same change as this migration) was additionally masking the
-- failure by silently returning an unpersisted row as if it had saved.
--
-- Separately, the Product Bible model's health_grade values are band labels
-- ("Healthy"/"Good"/"Needs Attention"/"At Risk"/"Critical"), not the original
-- single-letter grades — the existing CHECK constraint would reject every one
-- of them even once the missing columns above are added. Widened to a superset
-- so historical A-F rows (if any) remain valid alongside the current model.
--
-- A second, independent, compounding bug found while proving this fix against
-- real Postgres: health_scores, health_score_history, health_dimension_scores,
-- health_overrides, and health_alerts (all five tables migration 059 created)
-- were NEVER granted to service_role — migrations 060/061 only ever granted
-- them to `authenticated`. The FastAPI backend connects with the service-role
-- key (core/supabase_client.py), so every one of routers/health.py's 13
-- endpoints — not just calculate/recalculate-all — has been getting
-- "permission denied for table health_scores" against any real deployment,
-- regardless of the column drift above. Every other table in this schema
-- picked up its service_role grant from either migration 039 (tables that
-- existed at the time) or an explicit grant in the migration that created it
-- (e.g. 046's client_health_scores/client_health_overrides); the five Phase
-- 7-8-9 health tables are the one place that pattern was missed.

ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS compliance_health_score     INTEGER CHECK (compliance_health_score BETWEEN 0 AND 100);
ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS accounting_quality_score    INTEGER CHECK (accounting_quality_score BETWEEN 0 AND 100);
ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS work_progress_score         INTEGER CHECK (work_progress_score BETWEEN 0 AND 100);
ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS document_health_score       INTEGER CHECK (document_health_score BETWEEN 0 AND 100);
ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS ai_risk_signals_score       INTEGER CHECK (ai_risk_signals_score BETWEEN 0 AND 100);
ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS open_notices_score          INTEGER CHECK (open_notices_score BETWEEN 0 AND 100);
ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS client_responsiveness_score INTEGER CHECK (client_responsiveness_score BETWEEN 0 AND 100);

ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS dimensions           JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS grade                TEXT;
ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS trend                TEXT;
ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS hard_override        TEXT;
ALTER TABLE public.health_scores ADD COLUMN IF NOT EXISTS hard_override_reason TEXT;

ALTER TABLE public.health_scores DROP CONSTRAINT IF EXISTS health_scores_health_grade_check;
ALTER TABLE public.health_scores ADD CONSTRAINT health_scores_health_grade_check
    CHECK (health_grade IN ('A','B','C','D','F',
                            'Healthy','Good','Needs Attention','At Risk','Critical'));

COMMENT ON COLUMN public.health_scores.dimensions IS
    'Product Bible Ch.16: per-dimension {score, weight, weighted} breakdown, as returned by GET /api/health/clients/{id}/dimension-detail.';
COMMENT ON COLUMN public.health_scores.grade IS
    'Product Bible Ch.16 band label (Healthy/Good/Needs Attention/At Risk/Critical). health_grade carries the same value for backward compatibility with existing readers.';

GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.health_scores            TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.health_score_history     TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.health_dimension_scores  TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.health_overrides        TO service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE public.health_alerts           TO service_role;
