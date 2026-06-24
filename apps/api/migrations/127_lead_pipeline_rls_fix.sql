-- Migration 127: Lead / prospect pipeline — RLS firm-isolation fix
--
-- Problem: migration 059 (phase 7/8/9 intelligence layer) created the lead
-- pipeline tables with an RLS policy keyed off a JWT claim this system never
-- issues:
--
--     CREATE POLICY "firm_isolation" ON leads
--       USING (firm_id::text = auth.jwt()->>'firm_id');
--
-- firm_id is NOT a Supabase JWT claim in this project — it is resolved
-- server-side from the users table (core/auth.py) and, inside Postgres, via the
-- canonical helper get_my_firm_id() (migration 005). So auth.jwt()->>'firm_id'
-- is always NULL, the predicate is always false, and because the policy has no
-- WITH CHECK the USING clause also governs inserts. Once the per-user-JWT data
-- path (USE_USER_JWT) is active — as it now is in production — this means:
--   * INSERT -> "new row violates row-level security policy for table leads"
--   * SELECT -> zero rows (the pipeline always renders empty)
--   * UPDATE -> stage moves silently match no rows
--
-- Every other firm-scoped table (clients, engagements, fee_engagements, users,
-- firms, ...) already uses get_my_firm_id(). This migration brings the lead
-- pipeline + conversion tables onto that same proven pattern.
--
-- Scope: the lead/prospect pipeline and its conversion targets only. The other
-- migration-059 tables that back DIFFERENT features (entities / relationship
-- intelligence, health_*, ai_*, client_profiles, firm_profiles,
-- cross_client_matches) carry the identical latent defect and should be migrated
-- the same way when those features are exercised under per-user JWT — they are
-- intentionally left out of this focused fix.
--
-- Idempotent: drops the broken "firm_isolation" policy (created by 059) by name,
-- then (re)creates the canonical "<table>_firm_isolation" policy. The RESTRICTIVE
-- *_assignment_scope policies added in migration 084 are deliberately left in
-- place — they continue to layer assignment-level scoping on top. can_access_client(NULL)
-- returns true, so firm-scoped rows with a null client_id (e.g. lead-stage
-- lifecycle events) are unaffected.

-- leads ----------------------------------------------------------------------
DROP POLICY IF EXISTS firm_isolation       ON public.leads;
DROP POLICY IF EXISTS leads_firm_isolation ON public.leads;
CREATE POLICY leads_firm_isolation ON public.leads
  USING      (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- lead_contacts --------------------------------------------------------------
DROP POLICY IF EXISTS firm_isolation               ON public.lead_contacts;
DROP POLICY IF EXISTS lead_contacts_firm_isolation ON public.lead_contacts;
CREATE POLICY lead_contacts_firm_isolation ON public.lead_contacts
  USING      (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- lead_activities ------------------------------------------------------------
DROP POLICY IF EXISTS firm_isolation                 ON public.lead_activities;
DROP POLICY IF EXISTS lead_activities_firm_isolation ON public.lead_activities;
CREATE POLICY lead_activities_firm_isolation ON public.lead_activities
  USING      (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- proposals ------------------------------------------------------------------
DROP POLICY IF EXISTS firm_isolation           ON public.proposals;
DROP POLICY IF EXISTS proposals_firm_isolation ON public.proposals;
CREATE POLICY proposals_firm_isolation ON public.proposals
  USING      (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- onboarding_workflows -------------------------------------------------------
DROP POLICY IF EXISTS firm_isolation                      ON public.onboarding_workflows;
DROP POLICY IF EXISTS onboarding_workflows_firm_isolation ON public.onboarding_workflows;
CREATE POLICY onboarding_workflows_firm_isolation ON public.onboarding_workflows
  USING      (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- onboarding_tasks -----------------------------------------------------------
DROP POLICY IF EXISTS firm_isolation                  ON public.onboarding_tasks;
DROP POLICY IF EXISTS onboarding_tasks_firm_isolation ON public.onboarding_tasks;
CREATE POLICY onboarding_tasks_firm_isolation ON public.onboarding_tasks
  USING      (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- client_lifecycle_events ----------------------------------------------------
DROP POLICY IF EXISTS firm_isolation                         ON public.client_lifecycle_events;
DROP POLICY IF EXISTS client_lifecycle_events_firm_isolation ON public.client_lifecycle_events;
CREATE POLICY client_lifecycle_events_firm_isolation ON public.client_lifecycle_events
  USING      (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());

-- renewals -------------------------------------------------------------------
DROP POLICY IF EXISTS firm_isolation          ON public.renewals;
DROP POLICY IF EXISTS renewals_firm_isolation ON public.renewals;
CREATE POLICY renewals_firm_isolation ON public.renewals
  USING      (firm_id = get_my_firm_id())
  WITH CHECK (firm_id = get_my_firm_id());
