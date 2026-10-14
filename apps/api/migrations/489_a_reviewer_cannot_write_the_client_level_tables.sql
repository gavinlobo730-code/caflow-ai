-- Migration 489 — a Reviewer can no longer write the client-level tables
-- (security_privacy-34; ledger POST-B-005, third and last slice; the class `reviewer-writes-where-no-resource-allows-it`
-- ends here).
--
-- THE HOLE
--   Nine tables carry a firm policy and an assignment scope and no write tier: ai_insights, client_instructions,
--   compliance_records, government_notices, the three health tables and onboarding_workflows and renewals. A Reviewer
--   assigned to a client wrote them straight over PostgREST; the API never lets a Reviewer near them. A read-only
--   audit of every writer found no legitimate Reviewer write and no read that writes under the caller's sign-in (the
--   health scores are written only by POST routes, the lifecycle GETs write nothing, and the job writers use the
--   service role).
--
-- WHAT THIS DOES
--   RESTRICTIVE per-command policies asking `my_permission(resource, action, floor)`, with the pair each table's own
--   routes ask:
--
--     ai_insights                      report:write (Manager)
--     client_instructions              client_instruction:write (Executive)
--     compliance_records               compliance_record:write (Executive)
--     government_notices               compliance:write (Executive)
--     health_alerts, health_score_history, health_scores, onboarding_workflows, renewals
--                                      client:write (Manager)
--
-- WHAT CHANGES FOR AN EXECUTIVE
--   The health, onboarding and renewal tables and ai_insights are Manager-only in the API (client:write, report:write)
--   and the database let an Executive write them directly; those cells close too (the reviewed access expectation is
--   regenerated and its diff read). client_instructions, compliance_records and government_notices keep the Executive.
--
-- WHAT IT LEAVES ALONE: SELECT, every function, grant, table and row. No backfill.
--
-- Idempotent: DROP POLICY IF EXISTS before each CREATE, and the closing check fails the migration if any policy is
-- missing. Reversible: 489_..._rollback.sql drops them, which RE-OPENS the hole.
-- ── ai_insights ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "ai_insights_write_tier_insert" ON public.ai_insights;
CREATE POLICY "ai_insights_write_tier_insert" ON public.ai_insights
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('report', 'write', 'Manager'));

DROP POLICY IF EXISTS "ai_insights_write_tier_update" ON public.ai_insights;
CREATE POLICY "ai_insights_write_tier_update" ON public.ai_insights
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('report', 'write', 'Manager'))
  WITH CHECK (public.my_permission('report', 'write', 'Manager'));

DROP POLICY IF EXISTS "ai_insights_write_tier_delete" ON public.ai_insights;
CREATE POLICY "ai_insights_write_tier_delete" ON public.ai_insights
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('report', 'write', 'Manager'));

-- ── client_instructions ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "client_instructions_write_tier_insert" ON public.client_instructions;
CREATE POLICY "client_instructions_write_tier_insert" ON public.client_instructions
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('client_instruction', 'write', 'Executive'));

DROP POLICY IF EXISTS "client_instructions_write_tier_update" ON public.client_instructions;
CREATE POLICY "client_instructions_write_tier_update" ON public.client_instructions
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('client_instruction', 'write', 'Executive'))
  WITH CHECK (public.my_permission('client_instruction', 'write', 'Executive'));

DROP POLICY IF EXISTS "client_instructions_write_tier_delete" ON public.client_instructions;
CREATE POLICY "client_instructions_write_tier_delete" ON public.client_instructions
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('client_instruction', 'write', 'Executive'));

-- ── compliance_records ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "compliance_records_write_tier_insert" ON public.compliance_records;
CREATE POLICY "compliance_records_write_tier_insert" ON public.compliance_records
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('compliance_record', 'write', 'Executive'));

DROP POLICY IF EXISTS "compliance_records_write_tier_update" ON public.compliance_records;
CREATE POLICY "compliance_records_write_tier_update" ON public.compliance_records
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('compliance_record', 'write', 'Executive'))
  WITH CHECK (public.my_permission('compliance_record', 'write', 'Executive'));

DROP POLICY IF EXISTS "compliance_records_write_tier_delete" ON public.compliance_records;
CREATE POLICY "compliance_records_write_tier_delete" ON public.compliance_records
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('compliance_record', 'write', 'Executive'));

-- ── government_notices ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "government_notices_write_tier_insert" ON public.government_notices;
CREATE POLICY "government_notices_write_tier_insert" ON public.government_notices
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('compliance', 'write', 'Executive'));

DROP POLICY IF EXISTS "government_notices_write_tier_update" ON public.government_notices;
CREATE POLICY "government_notices_write_tier_update" ON public.government_notices
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('compliance', 'write', 'Executive'))
  WITH CHECK (public.my_permission('compliance', 'write', 'Executive'));

DROP POLICY IF EXISTS "government_notices_write_tier_delete" ON public.government_notices;
CREATE POLICY "government_notices_write_tier_delete" ON public.government_notices
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('compliance', 'write', 'Executive'));

-- ── health_alerts ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "health_alerts_write_tier_insert" ON public.health_alerts;
CREATE POLICY "health_alerts_write_tier_insert" ON public.health_alerts
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "health_alerts_write_tier_update" ON public.health_alerts;
CREATE POLICY "health_alerts_write_tier_update" ON public.health_alerts
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'))
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "health_alerts_write_tier_delete" ON public.health_alerts;
CREATE POLICY "health_alerts_write_tier_delete" ON public.health_alerts
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'));

-- ── health_score_history ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "health_score_history_write_tier_insert" ON public.health_score_history;
CREATE POLICY "health_score_history_write_tier_insert" ON public.health_score_history
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "health_score_history_write_tier_update" ON public.health_score_history;
CREATE POLICY "health_score_history_write_tier_update" ON public.health_score_history
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'))
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "health_score_history_write_tier_delete" ON public.health_score_history;
CREATE POLICY "health_score_history_write_tier_delete" ON public.health_score_history
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'));

-- ── health_scores ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "health_scores_write_tier_insert" ON public.health_scores;
CREATE POLICY "health_scores_write_tier_insert" ON public.health_scores
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "health_scores_write_tier_update" ON public.health_scores;
CREATE POLICY "health_scores_write_tier_update" ON public.health_scores
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'))
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "health_scores_write_tier_delete" ON public.health_scores;
CREATE POLICY "health_scores_write_tier_delete" ON public.health_scores
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'));

-- ── onboarding_workflows ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "onboarding_workflows_write_tier_insert" ON public.onboarding_workflows;
CREATE POLICY "onboarding_workflows_write_tier_insert" ON public.onboarding_workflows
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "onboarding_workflows_write_tier_update" ON public.onboarding_workflows;
CREATE POLICY "onboarding_workflows_write_tier_update" ON public.onboarding_workflows
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'))
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "onboarding_workflows_write_tier_delete" ON public.onboarding_workflows;
CREATE POLICY "onboarding_workflows_write_tier_delete" ON public.onboarding_workflows
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'));

-- ── renewals ─────────────────────────────────────────────────────────────
DROP POLICY IF EXISTS "renewals_write_tier_insert" ON public.renewals;
CREATE POLICY "renewals_write_tier_insert" ON public.renewals
  AS RESTRICTIVE FOR INSERT TO authenticated
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "renewals_write_tier_update" ON public.renewals;
CREATE POLICY "renewals_write_tier_update" ON public.renewals
  AS RESTRICTIVE FOR UPDATE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'))
  WITH CHECK (public.my_permission('client', 'write', 'Manager'));

DROP POLICY IF EXISTS "renewals_write_tier_delete" ON public.renewals;
CREATE POLICY "renewals_write_tier_delete" ON public.renewals
  AS RESTRICTIVE FOR DELETE TO authenticated
  USING (public.my_permission('client', 'write', 'Manager'));

-- ── the closing check: all 27 policies exist and every one is RESTRICTIVE ───────────────────────
DO $$
DECLARE
  n int;
BEGIN
  SELECT count(*) INTO n
    FROM pg_policies
   WHERE schemaname = 'public'
     AND permissive = 'RESTRICTIVE'
     AND policyname IN (
       'ai_insights_write_tier_insert',
       'ai_insights_write_tier_update',
       'ai_insights_write_tier_delete',
       'client_instructions_write_tier_insert',
       'client_instructions_write_tier_update',
       'client_instructions_write_tier_delete',
       'compliance_records_write_tier_insert',
       'compliance_records_write_tier_update',
       'compliance_records_write_tier_delete',
       'government_notices_write_tier_insert',
       'government_notices_write_tier_update',
       'government_notices_write_tier_delete',
       'health_alerts_write_tier_insert',
       'health_alerts_write_tier_update',
       'health_alerts_write_tier_delete',
       'health_score_history_write_tier_insert',
       'health_score_history_write_tier_update',
       'health_score_history_write_tier_delete',
       'health_scores_write_tier_insert',
       'health_scores_write_tier_update',
       'health_scores_write_tier_delete',
       'onboarding_workflows_write_tier_insert',
       'onboarding_workflows_write_tier_update',
       'onboarding_workflows_write_tier_delete',
       'renewals_write_tier_insert',
       'renewals_write_tier_update',
       'renewals_write_tier_delete');
  IF n <> 27 THEN
    RAISE EXCEPTION 'migration 489: expected 27 restrictive policies, found %', n;
  END IF;
END $$;
