-- Migration 062: RLS hardening — pre-beta production-readiness audit
--
-- FINDING (defense-in-depth gap, low severity):
-- 28 tables were created without `ENABLE ROW LEVEL SECURITY`, unlike the other
-- 139 tables in the schema which are all RLS-protected. These 28 tables are
-- currently only reachable via the FastAPI backend (service-role key, which
-- bypasses RLS and filters by firm_id at the repository layer). The frontend
-- never queries them directly, and the `authenticated` role holds no table
-- GRANT on any of them, so PostgreSQL already denies direct access before RLS
-- is evaluated. There is therefore no active cross-tenant exposure today.
--
-- However, the schema's security posture is "RLS on every table" and these 28
-- are the lone exceptions. Enabling RLS here makes them fail-closed: should a
-- future migration ever GRANT these tables to `authenticated` (e.g. a blanket
-- GRANT ON ALL TABLES), access stays correctly firm-scoped instead of leaking.
--
-- Service-role (backend) bypasses RLS, so enabling it changes nothing for the
-- running application — it is pure hardening.
--
-- Tables WITH a firm_id column get a firm-scoped policy: firm_id = get_my_firm_id().
-- Child tables WITHOUT firm_id (scoped via a parent FK) get fail-closed RLS
-- (RLS enabled, no permissive policy) — safe because `authenticated` has no
-- GRANT and the service-role backend bypasses RLS.

-- ─── firm-scoped tables (firm_id present) ────────────────────────────────────

DO $$
DECLARE
  t text;
  firm_scoped text[] := ARRAY[
    'ai_actions', 'ai_context_windows', 'ai_conversations', 'ai_feedback',
    'ai_memory_triggers', 'ai_messages', 'ai_recommendations', 'ai_summaries',
    'client_profile_history', 'pattern_anomalies', 'scheduler_runs',
    'task_recurring_configs', 'task_tags', 'task_templates',
    'task_timeline_events', 'time_entries', 'user_capacity',
    'workflow_approvals', 'workflow_executions', 'workflow_failures',
    'workflow_instances', 'workflow_schedules', 'workflow_templates',
    'year_end_reports'
  ];
BEGIN
  FOREACH t IN ARRAY firm_scoped LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = t) THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
      EXECUTE format('DROP POLICY IF EXISTS %I ON public.%I', t || '_firm_isolation', t);
      EXECUTE format(
        'CREATE POLICY %I ON public.%I FOR ALL TO authenticated '
        'USING (firm_id = get_my_firm_id()) '
        'WITH CHECK (firm_id = get_my_firm_id())',
        t || '_firm_isolation', t
      );
    END IF;
  END LOOP;
END $$;

-- ─── child tables (no firm_id) — fail-closed RLS ─────────────────────────────
-- Reachable only through the service-role backend (which bypasses RLS) and
-- joined to a firm-scoped parent. No permissive policy is added: any direct
-- `authenticated` access is denied. This matches deny-by-default hardening.

DO $$
DECLARE
  t text;
  child_tables text[] := ARRAY[
    'task_dependencies', 'workflow_action_logs',
    'workflow_conditions', 'workflow_triggers'
  ];
BEGIN
  FOREACH t IN ARRAY child_tables LOOP
    IF EXISTS (SELECT 1 FROM information_schema.tables
               WHERE table_schema = 'public' AND table_name = t) THEN
      EXECUTE format('ALTER TABLE public.%I ENABLE ROW LEVEL SECURITY', t);
    END IF;
  END LOOP;
END $$;
