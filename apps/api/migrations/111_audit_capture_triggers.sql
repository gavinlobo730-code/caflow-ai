-- PracticeSync AI — Migration 111: comprehensive database-level audit capture
--
-- Problem: the Audit Log is only as complete as services/audit_service.log_event,
-- which fires on backend mutation paths. But large parts of the app write DIRECTLY
-- to Supabase from the browser (firm profile, chart of accounts, journals, sales
-- invoices, payroll, TDS/GST/income-tax, MCA, clients, tasks, documents, …),
-- bypassing the backend entirely. Those user actions were never audited.
--
-- Fix: a generic AFTER INSERT/UPDATE/DELETE trigger on every firm-scoped business
-- table. It captures the acting user from auth.uid() (always present for browser
-- writes that carry the user's JWT) and writes an immutable audit_log row.
--
-- No double-logging: the trigger fires ONLY when auth.uid() IS NOT NULL — i.e. for
-- end-user (client-side) writes. Backend writes use the service-role key
-- (auth.uid() IS NULL) and are skipped here; they remain covered by
-- audit_service.log_event with richer, intent-level actions.
--   ⚠️  If USE_USER_JWT is ever turned ON (backend writes as the end user), revisit
--       this guard to avoid double-logging the paths that also call log_event.
--
-- Safety: the function is SECURITY DEFINER (so the audit INSERT bypasses the
-- Partner-only RLS on audit_log) and fully non-fatal — any error is swallowed so
-- auditing can never break the user's underlying write. Idempotent.
-- Rollback: 111_audit_capture_triggers_rollback.sql.

CREATE OR REPLACE FUNCTION public.audit_capture()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actor  uuid := auth.uid();
  v_email  text;
  v_firm   uuid;
  v_entity text;
  v_etype  text;
  v_action text;
  v_old    jsonb;
  v_new    jsonb;
BEGIN
  -- Only capture end-user (browser) writes. Service-role backend writes have a
  -- NULL auth.uid() and are audited in-app by audit_service.log_event.
  IF v_actor IS NULL THEN
    RETURN NULL;
  END IF;

  IF (TG_OP = 'INSERT') THEN
    v_action := 'create'; v_new := to_jsonb(NEW);
  ELSIF (TG_OP = 'UPDATE') THEN
    v_action := 'update'; v_new := to_jsonb(NEW); v_old := to_jsonb(OLD);
  ELSE
    v_action := 'delete'; v_old := to_jsonb(OLD);
  END IF;

  -- audit_log.firm_id is NOT NULL — skip any firm-less row.
  v_firm := nullif(coalesce(v_new->>'firm_id', v_old->>'firm_id'), '')::uuid;
  IF v_firm IS NULL THEN
    RETURN NULL;
  END IF;

  v_entity := coalesce(v_new->>'id', v_old->>'id');

  -- Normalise the table name to the app's singular entity vocabulary so events
  -- from triggers and from log_event share one set of filter values.
  v_etype := CASE TG_TABLE_NAME
    WHEN 'chart_of_accounts'   THEN 'account'
    WHEN 'accounts'            THEN 'account'
    WHEN 'compliance_calendar' THEN 'compliance'
    ELSE CASE
      WHEN TG_TABLE_NAME LIKE '%ies' THEN left(TG_TABLE_NAME, length(TG_TABLE_NAME) - 3) || 'y'
      WHEN TG_TABLE_NAME LIKE '%s'   THEN left(TG_TABLE_NAME, length(TG_TABLE_NAME) - 1)
      ELSE TG_TABLE_NAME
    END
  END;

  SELECT u.email INTO v_email FROM public.users u WHERE u.auth_user_id = v_actor LIMIT 1;

  INSERT INTO public.audit_log
    (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
  VALUES
    (v_firm, v_actor, v_email, v_etype, v_entity, v_action, v_old, v_new,
     jsonb_build_object('source', 'db_trigger', 'table', TG_TABLE_NAME));

  RETURN NULL;
EXCEPTION WHEN OTHERS THEN
  -- Auditing must never break the user's write.
  RETURN NULL;
END;
$$;

COMMENT ON FUNCTION public.audit_capture() IS
  'Module 9.0/M1: generic audit trigger. Logs end-user (auth.uid() present) writes '
  'to public.audit_log. Backend service-role writes are skipped (covered by '
  'audit_service.log_event). Non-fatal, SECURITY DEFINER, append-only.';

-- Attach the trigger to every firm-scoped business table that has an id, except
-- audit/event-feed, derived/computed, AI, health and line-item tables (those are
-- either machine-written, redundant with their parent, or would recurse).
DO $$
DECLARE
  r record;
  excluded text[] := ARRAY[
    -- must never audit the audit log itself (recursion)
    'audit_log',
    -- existing logs / event feeds / delivery & run logs
    'activity_logs','login_events',
    'client_timeline_events','task_timeline_events','client_lifecycle_events','year_end_review_events',
    'customer_payment_events','invoice_deliveries','customer_statement_deliveries',
    'scheduler_runs','recurring_invoice_runs','workflow_executions','workflow_failures',
    'gst_sync_jobs','gst_portal_snapshots','tally_migration_jobs','tally_migration_items',
    -- derived / computed
    'ledger_balances',
    'client_health_scores','client_health_overrides','health_alerts','health_dimension_scores',
    'health_overrides','health_scores','health_score_history',
    'client_profiles','firm_profiles','client_profile_history',
    -- AI-generated
    'ai_actions','ai_context_windows','ai_conversations','ai_evidence','ai_feedback','ai_insights',
    'ai_memory_triggers','ai_messages','ai_recommendations','ai_signals','ai_summaries','ai_trigger_registry',
    'auto_journal_suggestions','pattern_anomalies','cross_client_matches',
    -- system noise / line-item child tables
    'notifications','demo_filings','journal_entry_lines'
  ];
BEGIN
  FOR r IN
    SELECT c.table_name
    FROM information_schema.columns c
    JOIN information_schema.tables t
      ON t.table_schema = c.table_schema AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE'
    WHERE c.table_schema = 'public'
      AND c.column_name = 'firm_id'
      AND EXISTS (
        SELECT 1 FROM information_schema.columns c2
        WHERE c2.table_schema = 'public' AND c2.table_name = c.table_name AND c2.column_name = 'id'
      )
      AND NOT (c.table_name = ANY(excluded))
    GROUP BY c.table_name
  LOOP
    EXECUTE format('DROP TRIGGER IF EXISTS trg_audit_capture ON public.%I', r.table_name);
    EXECUTE format(
      'CREATE TRIGGER trg_audit_capture AFTER INSERT OR UPDATE OR DELETE ON public.%I '
      'FOR EACH ROW EXECUTE FUNCTION public.audit_capture()', r.table_name);
  END LOOP;
END $$;

-- The firms table is the firm itself: it has no firm_id column (its id IS the
-- firm id), so the generic loop above skips it. Give it a dedicated trigger so
-- firm-profile edits (Settings / onboarding) are audited too.
CREATE OR REPLACE FUNCTION public.audit_capture_firm()
RETURNS TRIGGER
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
DECLARE
  v_actor  uuid := auth.uid();
  v_email  text;
  v_firm   uuid;
  v_action text;
  v_old    jsonb;
  v_new    jsonb;
BEGIN
  IF v_actor IS NULL THEN RETURN NULL; END IF;

  IF (TG_OP = 'INSERT') THEN
    v_action := 'create'; v_new := to_jsonb(NEW);
  ELSIF (TG_OP = 'UPDATE') THEN
    v_action := 'update'; v_new := to_jsonb(NEW); v_old := to_jsonb(OLD);
  ELSE
    v_action := 'delete'; v_old := to_jsonb(OLD);
  END IF;

  v_firm := nullif(coalesce(v_new->>'id', v_old->>'id'), '')::uuid;
  IF v_firm IS NULL THEN RETURN NULL; END IF;

  SELECT u.email INTO v_email FROM public.users u WHERE u.auth_user_id = v_actor LIMIT 1;

  INSERT INTO public.audit_log
    (firm_id, actor_id, actor_email, entity_type, entity_id, action, old_data, new_data, metadata)
  VALUES
    (v_firm, v_actor, v_email, 'firm', v_firm::text, v_action, v_old, v_new,
     jsonb_build_object('source', 'db_trigger', 'table', 'firms'));

  RETURN NULL;
EXCEPTION WHEN OTHERS THEN
  RETURN NULL;
END;
$$;

COMMENT ON FUNCTION public.audit_capture_firm() IS
  'Module 9.0/M1: audit trigger for the firms table (firm_id = id). Logs end-user firm-profile changes to public.audit_log. Companion to audit_capture().';

DROP TRIGGER IF EXISTS trg_audit_capture ON public.firms;
CREATE TRIGGER trg_audit_capture AFTER INSERT OR UPDATE OR DELETE ON public.firms
  FOR EACH ROW EXECUTE FUNCTION public.audit_capture_firm();
