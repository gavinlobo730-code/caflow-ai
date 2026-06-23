-- Migration 121: link onboarding workflows back to their originating lead and
-- signed engagement letter, so the Lead → Engagement → Signed → Onboarding → Client
-- chain has no orphan records. Additive, idempotent.

ALTER TABLE public.onboarding_workflows ADD COLUMN IF NOT EXISTS lead_id UUID;
ALTER TABLE public.onboarding_workflows ADD COLUMN IF NOT EXISTS engagement_id UUID;

CREATE INDEX IF NOT EXISTS idx_onboarding_workflows_lead
  ON public.onboarding_workflows (lead_id) WHERE lead_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_onboarding_workflows_engagement
  ON public.onboarding_workflows (engagement_id) WHERE engagement_id IS NOT NULL;
