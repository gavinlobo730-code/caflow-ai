-- 154 — Fix RLS policies keyed on a firm_id JWT claim this system never issues
-- (fixes audit finding F20; Tier 2 R2.6).
--
-- Migrations 059 (phase 7/8/9 intelligence layer), 067 (year-end) and 071
-- (workflow engine / AI copilot / AI memory) created RLS policies of the shape:
--
--     CREATE POLICY "firm_isolation" ON <table>
--       USING (firm_id::text = auth.jwt()->>'firm_id');
--
-- firm_id is NOT a Supabase JWT claim this project issues — it is resolved
-- server-side from the users table (core/auth.py) and, inside Postgres, via
-- the canonical helper get_my_firm_id() (migration 005, fixed in 019). So
-- auth.jwt()->>'firm_id' is always NULL, the predicate is always false, and
-- because none of these policies carry a WITH CHECK, the USING clause also
-- silently governs inserts (deny-all in every direction).
--
-- Migration 127 already fixed 8 of 059's tables (the lead/prospect pipeline)
-- onto get_my_firm_id() and documented that the remaining 059 tables — plus
-- all of 067 and 071 — carry the identical defect. This migration finishes
-- that job for every remaining table.
--
-- Reachability today: none of these tables are queried directly from the
-- frontend (`apps/web`) — they are backend-only, and the backend's
-- get_supabase() (core/supabase_client.py) returns the service-role client
-- (bypasses RLS) whenever USE_USER_JWT is off, which is always, today. So this
-- is a real but currently-unreachable defect (deny-all, not allow-all) — it
-- matters for the day USE_USER_JWT is cut over (R2.4) and for any direct
-- anon/authenticated-key access (PostgREST, a future mobile client, etc.).
--
-- Idempotent: drops every old broken policy (by every name it was ever created
-- under, across 059/067/071) and creates ONE canonical `<table>_firm_isolation`
-- policy per table using the proven get_my_firm_id() predicate, matching the
-- pattern already used successfully on dozens of other tables (clients, firms,
-- engagements, fee_engagements, ...) and by migration 127. Table-existence is
-- checked before every ALTER/DROP/CREATE, since some of these tables' creating
-- migrations (068, 070) are documented, already-tracked apply failures
-- (test_migrations_apply.py EXPECTED_MIGRATION_FAILURES) and may not exist in
-- every environment.

-- ── Drop every previously-created broken policy, by its original name ────────
DO $$
DECLARE
  r record;
BEGIN
  FOR r IN
    SELECT * FROM (VALUES
      -- from 059_phase7_8_9_intelligence_layer.sql (all named "firm_isolation")
      ('engagement_letters',            'firm_isolation'),
      ('entities',                      'firm_isolation'),
      ('entity_roles',                  'firm_isolation'),
      ('entity_relationships',          'firm_isolation'),
      ('entity_client_links',           'firm_isolation'),
      ('entity_addresses',              'firm_isolation'),
      ('entity_documents',              'firm_isolation'),
      ('cross_client_matches',          'firm_isolation'),
      ('health_scores',                 'firm_isolation'),
      ('health_score_history',          'firm_isolation'),
      ('health_dimension_scores',       'firm_isolation'),
      ('health_overrides',              'firm_isolation'),
      ('health_alerts',                 'firm_isolation'),
      ('ai_signals',                    'firm_isolation'),
      ('ai_evidence',                   'firm_isolation'),
      ('ai_trigger_registry',           'firm_isolation'),
      ('client_profiles',               'firm_isolation'),
      ('firm_profiles',                 'firm_isolation'),
      -- from 067_phase6_year_end.sql (uniquely named per table)
      ('year_end_engagements',          'yee_firm_isolation'),
      ('year_end_checklists',           'yec_firm_isolation'),
      ('year_end_adjustments',          'yea_firm_isolation'),
      ('account_group_mappings',        'agm_firm_isolation'),
      ('financial_statement_versions',  'fsv_firm_isolation'),
      ('notes_to_accounts',             'nta_firm_isolation'),
      ('year_end_reviews',              'yer_firm_isolation'),
      ('year_end_exports',              'yex_firm_isolation'),
      -- from 071_rls_policies.sql (uniquely named per table)
      ('workflow_templates',            'wft_firm_isolation'),
      ('workflow_instances',            'wfi_firm_isolation'),
      ('workflow_executions',           'wfe_firm_isolation'),
      ('workflow_failures',             'wff_firm_isolation'),
      ('workflow_approvals',            'wfa_firm_isolation'),
      ('workflow_schedules',            'wfs_firm_isolation'),
      ('ai_conversations',              'aic_firm_isolation'),
      ('ai_messages',                   'aim_firm_isolation'),
      ('ai_context_windows',            'aicw_firm_isolation'),
      ('ai_summaries',                  'ais_firm_isolation'),
      ('ai_recommendations',            'air_firm_isolation'),
      ('ai_actions',                    'aiact_firm_isolation'),
      ('ai_feedback',                   'aifb_firm_isolation'),
      ('client_profiles',               'cp_firm_isolation'),   -- 071's duplicate policy on the same table as 059's
      ('client_profile_history',        'cph_firm_isolation'),
      ('firm_profiles',                 'fp_firm_isolation'),   -- 071's duplicate policy on the same table as 059's
      ('ai_memory_triggers',            'amt_firm_isolation'),
      ('pattern_anomalies',             'pa_firm_isolation'),
      ('year_end_reports',              'yer_firm_isolation')
    ) AS old_policies(table_name, policy_name)
  LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = r.table_name) THEN
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', r.policy_name, r.table_name);
    END IF;
  END LOOP;
END $$;

-- ── (Re)create ONE canonical, correct policy per table ───────────────────────
DO $$
DECLARE
  t text;
  tables text[] := ARRAY[
    'engagement_letters', 'entities', 'entity_roles', 'entity_relationships',
    'entity_client_links', 'entity_addresses', 'entity_documents',
    'cross_client_matches', 'health_scores', 'health_score_history',
    'health_dimension_scores', 'health_overrides', 'health_alerts',
    'ai_signals', 'ai_evidence', 'ai_trigger_registry', 'client_profiles',
    'firm_profiles', 'year_end_engagements', 'year_end_checklists',
    'year_end_adjustments', 'account_group_mappings',
    'financial_statement_versions', 'notes_to_accounts', 'year_end_reviews',
    'year_end_exports', 'workflow_templates', 'workflow_instances',
    'workflow_executions', 'workflow_failures', 'workflow_approvals',
    'workflow_schedules', 'ai_conversations', 'ai_messages',
    'ai_context_windows', 'ai_summaries', 'ai_recommendations', 'ai_actions',
    'ai_feedback', 'client_profile_history', 'ai_memory_triggers',
    'pattern_anomalies', 'year_end_reports'
  ];
  policy_name text;
BEGIN
  FOREACH t IN ARRAY tables LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = t) THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
      policy_name := t || '_firm_isolation';
      IF NOT EXISTS (SELECT 1 FROM pg_policies
                     WHERE schemaname = 'public' AND tablename = t AND policyname = policy_name) THEN
        EXECUTE format(
          'CREATE POLICY %I ON public.%I FOR ALL USING (firm_id = get_my_firm_id()) WITH CHECK (firm_id = get_my_firm_id())',
          policy_name, t);
      END IF;
    END IF;
  END LOOP;
END $$;
