-- Migration 125: Engagement tables — RLS, policies, grants, FKs, UNIQUE
--
-- Problem: migration 115 created engagement_templates, engagements, engagement_events
-- with ZERO row-level security, no policies, no grants, and no foreign key constraints.
-- Every other firm-scoped business table in this project has all three. Without RLS,
-- a user from Firm A can read or modify Firm B's engagement letters via direct
-- Supabase browser queries (same cross-tenant vulnerability fixed in Sprint 1 C1).
--
-- Fix: idempotent — uses DO blocks for FK constraints (ADD CONSTRAINT IF NOT EXISTS
-- is not valid Postgres syntax); uses CREATE POLICY IF NOT EXISTS (Postgres 9.5+).

-- ── Row Level Security ────────────────────────────────────────────────────────

ALTER TABLE public.engagement_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.engagements          ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.engagement_events    ENABLE ROW LEVEL SECURITY;

-- ── Policies (firm isolation via get_my_firm_id()) ───────────────────────────

-- engagement_templates
DROP POLICY IF EXISTS engagement_templates_firm_isolation ON public.engagement_templates;
CREATE POLICY engagement_templates_firm_isolation
  ON public.engagement_templates
  USING      (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- engagements
DROP POLICY IF EXISTS engagements_firm_isolation ON public.engagements;
CREATE POLICY engagements_firm_isolation
  ON public.engagements
  USING      (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- engagement_events
DROP POLICY IF EXISTS engagement_events_firm_isolation ON public.engagement_events;
CREATE POLICY engagement_events_firm_isolation
  ON public.engagement_events
  USING      (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- ── Grants ────────────────────────────────────────────────────────────────────

GRANT SELECT, INSERT, UPDATE, DELETE ON public.engagement_templates TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.engagements            TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.engagement_events      TO authenticated;

-- ── Foreign Keys ─────────────────────────────────────────────────────────────
-- All wrapped in DO blocks because ADD CONSTRAINT IF NOT EXISTS is not valid SQL.

-- engagements.lead_id → leads.id (optional; set null on lead deletion)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_engagements_lead'
  ) THEN
    ALTER TABLE public.engagements
      ADD CONSTRAINT fk_engagements_lead
      FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE SET NULL;
  END IF;
END $$;

-- engagements.client_id → clients.id (optional; set null on client deletion)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_engagements_client'
  ) THEN
    ALTER TABLE public.engagements
      ADD CONSTRAINT fk_engagements_client
      FOREIGN KEY (client_id) REFERENCES public.clients(id) ON DELETE SET NULL;
  END IF;
END $$;

-- engagements.template_id → engagement_templates.id (optional; set null on template deletion)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_engagements_template'
  ) THEN
    ALTER TABLE public.engagements
      ADD CONSTRAINT fk_engagements_template
      FOREIGN KEY (template_id) REFERENCES public.engagement_templates(id) ON DELETE SET NULL;
  END IF;
END $$;

-- engagement_events.engagement_id → engagements.id (cascade: events go with engagement)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_engagement_events_engagement'
  ) THEN
    ALTER TABLE public.engagement_events
      ADD CONSTRAINT fk_engagement_events_engagement
      FOREIGN KEY (engagement_id) REFERENCES public.engagements(id) ON DELETE CASCADE;
  END IF;
END $$;

-- onboarding_workflows.engagement_id → engagements.id (set null; was added in migration 121)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_onboarding_engagement'
  ) THEN
    ALTER TABLE public.onboarding_workflows
      ADD CONSTRAINT fk_onboarding_engagement
      FOREIGN KEY (engagement_id) REFERENCES public.engagements(id) ON DELETE SET NULL;
  END IF;
END $$;

-- onboarding_workflows.lead_id → leads.id (set null on lead deletion)
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'fk_onboarding_lead'
  ) THEN
    ALTER TABLE public.onboarding_workflows
      ADD CONSTRAINT fk_onboarding_lead
      FOREIGN KEY (lead_id) REFERENCES public.leads(id) ON DELETE SET NULL;
  END IF;
END $$;

-- ── UNIQUE: one engagement_number per firm ────────────────────────────────────
-- Uses a partial unique index (CREATE UNIQUE INDEX IF NOT EXISTS is valid Postgres).
-- Enforces that two letters in the same firm cannot share the same number,
-- even if generated concurrently.
CREATE UNIQUE INDEX IF NOT EXISTS engagements_firm_number_unique
  ON public.engagements (firm_id, engagement_number);
