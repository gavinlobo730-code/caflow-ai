-- 011_rls_policies.sql
-- Security backfill: Row-Level Security for Phase 10 (Workflow Engine),
-- Phase 11 (AI Copilot) and Phase 13 (AI Memory) tables.
--
-- Idempotent — safe to run multiple times.
-- Uses the same firm-isolation pattern established in 007_phase6_year_end.sql:
--   firm_id::text = (auth.jwt() ->> 'firm_id')
--
-- Every policy is wrapped in a DO block so a re-run silently skips duplicates.

-- ═══════════════════════════════════════════════════════════════════════════════
-- HELPER: idempotent policy creation
-- ═══════════════════════════════════════════════════════════════════════════════
-- Each block follows the pattern:
--   1. ENABLE ROW LEVEL SECURITY (idempotent in Postgres)
--   2. CREATE POLICY inside DO/EXCEPTION WHEN duplicate_object block

-- ═══════════════════════════════════════════════════════════════════════════════
-- PHASE 10 — Workflow Engine (008_workflow_engine.sql)
-- Tables: workflow_templates, workflow_instances, workflow_executions,
--         workflow_failures, workflow_approvals, workflow_schedules
-- Note:  workflow_steps, workflow_triggers, workflow_conditions, workflow_action_logs
--        have no firm_id column (they cascade from template/instance).
--        They are protected by the parent table's RLS; no direct policy needed.
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── workflow_templates ────────────────────────────────────────────────────────
ALTER TABLE workflow_templates ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "wft_firm_isolation"
    ON workflow_templates FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── workflow_instances ────────────────────────────────────────────────────────
ALTER TABLE workflow_instances ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "wfi_firm_isolation"
    ON workflow_instances FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── workflow_executions ───────────────────────────────────────────────────────
ALTER TABLE workflow_executions ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "wfe_firm_isolation"
    ON workflow_executions FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── workflow_failures ─────────────────────────────────────────────────────────
ALTER TABLE workflow_failures ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "wff_firm_isolation"
    ON workflow_failures FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── workflow_approvals ────────────────────────────────────────────────────────
ALTER TABLE workflow_approvals ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "wfa_firm_isolation"
    ON workflow_approvals FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── workflow_schedules ────────────────────────────────────────────────────────
ALTER TABLE workflow_schedules ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "wfs_firm_isolation"
    ON workflow_schedules FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ═══════════════════════════════════════════════════════════════════════════════
-- PHASE 11 — AI Copilot Platform (009_ai_copilot.sql)
-- Tables: ai_conversations, ai_messages, ai_context_windows, ai_summaries,
--         ai_recommendations, ai_actions, ai_feedback
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── ai_conversations ──────────────────────────────────────────────────────────
ALTER TABLE ai_conversations ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "aic_firm_isolation"
    ON ai_conversations FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── ai_messages ───────────────────────────────────────────────────────────────
ALTER TABLE ai_messages ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "aim_firm_isolation"
    ON ai_messages FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── ai_context_windows ────────────────────────────────────────────────────────
ALTER TABLE ai_context_windows ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "aicw_firm_isolation"
    ON ai_context_windows FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── ai_summaries ──────────────────────────────────────────────────────────────
ALTER TABLE ai_summaries ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "ais_firm_isolation"
    ON ai_summaries FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── ai_recommendations ────────────────────────────────────────────────────────
ALTER TABLE ai_recommendations ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "air_firm_isolation"
    ON ai_recommendations FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── ai_actions ────────────────────────────────────────────────────────────────
ALTER TABLE ai_actions ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "aiact_firm_isolation"
    ON ai_actions FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── ai_feedback ───────────────────────────────────────────────────────────────
ALTER TABLE ai_feedback ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "aifb_firm_isolation"
    ON ai_feedback FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ═══════════════════════════════════════════════════════════════════════════════
-- PHASE 13 — AI Memory & Compounding Intelligence (010_ai_memory.sql)
-- Tables: client_profiles, client_profile_history, firm_profiles,
--         ai_memory_triggers, pattern_anomalies, year_end_reports
-- ═══════════════════════════════════════════════════════════════════════════════

-- ── client_profiles ───────────────────────────────────────────────────────────
ALTER TABLE client_profiles ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "cp_firm_isolation"
    ON client_profiles FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── client_profile_history ────────────────────────────────────────────────────
ALTER TABLE client_profile_history ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "cph_firm_isolation"
    ON client_profile_history FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── firm_profiles ─────────────────────────────────────────────────────────────
-- firm_profiles has a UNIQUE constraint on firm_id; one row per firm.
-- The policy ensures a firm can only see/modify its own profile row.
ALTER TABLE firm_profiles ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "fp_firm_isolation"
    ON firm_profiles FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── ai_memory_triggers ────────────────────────────────────────────────────────
ALTER TABLE ai_memory_triggers ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "amt_firm_isolation"
    ON ai_memory_triggers FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── pattern_anomalies ─────────────────────────────────────────────────────────
ALTER TABLE pattern_anomalies ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "pa_firm_isolation"
    ON pattern_anomalies FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;

-- ── year_end_reports ──────────────────────────────────────────────────────────
-- Note: this table is distinct from year_end_engagements (Phase 6).
-- It stores AI-generated planning reports; RLS is essential to prevent
-- cross-firm leakage of sensitive financial narrative.
ALTER TABLE year_end_reports ENABLE ROW LEVEL SECURITY;

DO $$ BEGIN
  CREATE POLICY "yer_firm_isolation"
    ON year_end_reports FOR ALL
    USING (firm_id::text = (auth.jwt() ->> 'firm_id'));
EXCEPTION WHEN duplicate_object THEN NULL;
END $$;
