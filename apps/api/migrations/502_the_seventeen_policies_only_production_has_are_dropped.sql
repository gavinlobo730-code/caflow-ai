-- Migration 502: drop the seventeen `firm_iso_*` policies that exist only in production
-- (ledger POST-A-015, from the 13-09-2026 declaring-what-production-enforces audit).
--
-- WHAT WAS WRONG
--   The production policy snapshot holds seventeen policies that no migration declares: seven `firm_iso_ai_*` on the AI
--   tables and ten `firm_iso_wf_*` on the workflow tables. All are PERMISSIVE, for every command, for PUBLIC. Their
--   predicate reads `current_setting('app.current_firm_id', true)`, a setting nothing in this product sets, so on every
--   request it is NULL and `firm_id = NULL` admits nothing. They are harmless today and a trap tomorrow: a policy the
--   migrations do not know is one a future `DROP POLICY` by declared name misses, one that no reader of the migrations can
--   see, and one that starts admitting rows the moment anything (a function, a pooled connection) sets that setting. Read
--   from production's catalogue on 17-10-2026, all seventeen are still there; migration 319 deliberately declared none of
--   them.
--
-- WHAT THIS DOES
--   `DROP POLICY IF EXISTS` for each of the seventeen, on its own table, and a closing check that fails the migration (and
--   so the deploy) if any `firm_iso_*` policy is left. A database built from the migrations never had them, so there it
--   changes nothing; on production it removes them. (`workflow_conditions` and `workflow_triggers` exist in production and not
--   in a database built from the migrations; `DROP POLICY IF EXISTS` on a table that is not there is a notice, not an error.)
--
-- WHAT STAYS, AND WHY NOTHING THAT WORKS TODAY MOVES (each read from production on 17-10-2026)
--   * Fifteen of the seventeen tables keep their real firm-isolation policy (`firm_id = get_my_firm_id()`, or for
--     `workflow_action_logs` and `workflow_steps` the same through the parent row, and for `workflow_templates` the same
--     OR a system template); the dropped policy was an OR beside it that admitted nothing.
--   * `workflow_conditions` and `workflow_triggers` have NO other policy in production. Migration 062 declares them
--     fail-closed on purpose ("no permissive policy is added: any direct `authenticated` access is denied... reachable only
--     through the service-role backend"). The dropped policy let any signed-in member read the conditions and triggers of
--     SYSTEM workflow templates; no code reads either table (a search of `apps/api` and `apps/web` finds only a docstring),
--     so dropping it makes production what 062 declares and removes a read nobody uses.
--   * No privilege, row, column, function or other policy changes.
--
-- Idempotent. Reversible: 502_..._rollback.sql recreates the seventeen exactly as production holds them, which RE-ADDS the
-- trap, and is here so the drop is a decision that can be undone.

DROP POLICY IF EXISTS "firm_iso_ai_actions" ON public.ai_actions;
DROP POLICY IF EXISTS "firm_iso_ai_context_windows" ON public.ai_context_windows;
DROP POLICY IF EXISTS "firm_iso_ai_conversations" ON public.ai_conversations;
DROP POLICY IF EXISTS "firm_iso_ai_feedback" ON public.ai_feedback;
DROP POLICY IF EXISTS "firm_iso_ai_messages" ON public.ai_messages;
DROP POLICY IF EXISTS "firm_iso_ai_recommendations" ON public.ai_recommendations;
DROP POLICY IF EXISTS "firm_iso_ai_summaries" ON public.ai_summaries;

DROP POLICY IF EXISTS "firm_iso_wf_action_logs" ON public.workflow_action_logs;
DROP POLICY IF EXISTS "firm_iso_wf_approvals" ON public.workflow_approvals;
DROP POLICY IF EXISTS "firm_iso_wf_conditions" ON public.workflow_conditions;
DROP POLICY IF EXISTS "firm_iso_wf_executions" ON public.workflow_executions;
DROP POLICY IF EXISTS "firm_iso_wf_failures" ON public.workflow_failures;
DROP POLICY IF EXISTS "firm_iso_wf_instances" ON public.workflow_instances;
DROP POLICY IF EXISTS "firm_iso_wf_schedules" ON public.workflow_schedules;
DROP POLICY IF EXISTS "firm_iso_wf_steps" ON public.workflow_steps;
DROP POLICY IF EXISTS "firm_iso_wf_templates" ON public.workflow_templates;
DROP POLICY IF EXISTS "firm_iso_wf_triggers" ON public.workflow_triggers;

DO $$
DECLARE
  left_over text;
BEGIN
  SELECT string_agg(tablename || '.' || policyname, ', ' ORDER BY tablename, policyname) INTO left_over
    FROM pg_policies WHERE schemaname = 'public' AND policyname LIKE 'firm\_iso\_%';
  IF left_over IS NOT NULL THEN
    RAISE EXCEPTION 'migration 502: firm_iso policies are still in place: %', left_over;
  END IF;
END $$;
