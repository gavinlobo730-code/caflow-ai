-- Rollback for migration 489: the 27 write-tier policies it added are dropped. This RE-OPENS the hole: a Reviewer
-- assigned to a client can again write that client's insights, instructions, compliance records, notices, health
-- records, onboarding workflows and renewals over PostgREST.

DROP POLICY IF EXISTS "ai_insights_write_tier_insert" ON public.ai_insights;
DROP POLICY IF EXISTS "ai_insights_write_tier_update" ON public.ai_insights;
DROP POLICY IF EXISTS "ai_insights_write_tier_delete" ON public.ai_insights;
DROP POLICY IF EXISTS "client_instructions_write_tier_insert" ON public.client_instructions;
DROP POLICY IF EXISTS "client_instructions_write_tier_update" ON public.client_instructions;
DROP POLICY IF EXISTS "client_instructions_write_tier_delete" ON public.client_instructions;
DROP POLICY IF EXISTS "compliance_records_write_tier_insert" ON public.compliance_records;
DROP POLICY IF EXISTS "compliance_records_write_tier_update" ON public.compliance_records;
DROP POLICY IF EXISTS "compliance_records_write_tier_delete" ON public.compliance_records;
DROP POLICY IF EXISTS "government_notices_write_tier_insert" ON public.government_notices;
DROP POLICY IF EXISTS "government_notices_write_tier_update" ON public.government_notices;
DROP POLICY IF EXISTS "government_notices_write_tier_delete" ON public.government_notices;
DROP POLICY IF EXISTS "health_alerts_write_tier_insert" ON public.health_alerts;
DROP POLICY IF EXISTS "health_alerts_write_tier_update" ON public.health_alerts;
DROP POLICY IF EXISTS "health_alerts_write_tier_delete" ON public.health_alerts;
DROP POLICY IF EXISTS "health_score_history_write_tier_insert" ON public.health_score_history;
DROP POLICY IF EXISTS "health_score_history_write_tier_update" ON public.health_score_history;
DROP POLICY IF EXISTS "health_score_history_write_tier_delete" ON public.health_score_history;
DROP POLICY IF EXISTS "health_scores_write_tier_insert" ON public.health_scores;
DROP POLICY IF EXISTS "health_scores_write_tier_update" ON public.health_scores;
DROP POLICY IF EXISTS "health_scores_write_tier_delete" ON public.health_scores;
DROP POLICY IF EXISTS "onboarding_workflows_write_tier_insert" ON public.onboarding_workflows;
DROP POLICY IF EXISTS "onboarding_workflows_write_tier_update" ON public.onboarding_workflows;
DROP POLICY IF EXISTS "onboarding_workflows_write_tier_delete" ON public.onboarding_workflows;
DROP POLICY IF EXISTS "renewals_write_tier_insert" ON public.renewals;
DROP POLICY IF EXISTS "renewals_write_tier_update" ON public.renewals;
DROP POLICY IF EXISTS "renewals_write_tier_delete" ON public.renewals;
