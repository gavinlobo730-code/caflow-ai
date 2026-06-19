-- Migration 095: Targeted Grant Reconciliation
-- Grants least-privilege access to authenticated users on tables that had no
-- SELECT grant. RLS policies on each table continue to enforce row-level firm/client
-- isolation — grants only lift the table-level permission barrier.
-- platform_admins and platform_audit are intentionally excluded.
-- Idempotent (GRANT is idempotent in Postgres).

-- ── Reference / read-only data ────────────────────────────────────────────────
GRANT SELECT ON hsn_master           TO authenticated;
GRANT SELECT ON tds_section_limits   TO authenticated;
GRANT SELECT ON task_templates       TO authenticated;
GRANT SELECT ON scheduler_runs       TO authenticated;

-- ── AI / intelligence tables ──────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_insights          TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_conversations     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_messages          TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_summaries         TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_actions           TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_feedback          TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_memory_triggers   TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_recommendations   TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON ai_context_windows   TO authenticated;
GRANT SELECT                         ON pattern_anomalies    TO authenticated;

-- ── Compliance ────────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON compliance_tasks     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON compliance_records   TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON filings              TO authenticated;

-- ── Client data ───────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON client_profiles         TO authenticated;
GRANT SELECT, INSERT                 ON client_profile_history  TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON documents               TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON document_requests       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON document_extractions    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON document_risks          TO authenticated;

-- ── Tax ───────────────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON gstr1_returns   TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON gstr2a_records  TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON gstr3b_returns  TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON gst_challans    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON tds_challans    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON tds_returns     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON tds_certificates TO authenticated;

-- ── MCA ───────────────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON mca_companies  TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON mca_directors  TO authenticated;

-- ── Accounting / Finance ──────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON fixed_assets        TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON fixed_deposits      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON loans               TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON bank_reconciliations TO authenticated;
GRANT SELECT, INSERT, UPDATE         ON ledger_balances     TO authenticated;
GRANT SELECT, INSERT, UPDATE         ON invoice_sequences   TO authenticated;

-- ── Firm management ───────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON firm_profiles       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON team_members        TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON user_capacity       TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON pending_invites     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON permission_grants   TO authenticated;

-- ── Assignments / scheduling ──────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON user_client_assignments TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON escalation_rules        TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON assignment_rules        TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON scheduled_reports       TO authenticated;

-- ── Tasks (extended tables) ───────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON task_tags              TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON task_dependencies      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON task_recurring_configs TO authenticated;
GRANT SELECT, INSERT                 ON task_timeline_events   TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON task_escalations       TO authenticated;

-- ── Notifications / reminders ─────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON notifications TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON reminders     TO authenticated;

-- ── Time tracking ─────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON time_entries TO authenticated;

-- ── Workflows ─────────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON workflows              TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_steps         TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_templates     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_schedules     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_triggers      TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_conditions    TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_approvals     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_instances     TO authenticated;
GRANT SELECT, INSERT, UPDATE, DELETE ON workflow_executions    TO authenticated;
GRANT SELECT, INSERT                 ON workflow_action_logs   TO authenticated;
GRANT SELECT, INSERT                 ON workflow_failures      TO authenticated;

-- ── Automation ────────────────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON automation_rules      TO authenticated;
GRANT SELECT, INSERT                 ON automation_executions TO authenticated;

-- ── Year end / reporting ──────────────────────────────────────────────────────
GRANT SELECT, INSERT, UPDATE, DELETE ON year_end_reports  TO authenticated;

-- ── Activity logs (append-only audit) ────────────────────────────────────────
GRANT SELECT, INSERT ON activity_logs TO authenticated;

-- ── Service-role catch-up for tables that were also missing service_role grants
GRANT ALL ON shared_reports              TO service_role;
GRANT ALL ON portal_messages             TO service_role;
GRANT ALL ON compliance_tasks            TO service_role;
GRANT ALL ON compliance_records          TO service_role;
GRANT ALL ON document_requests           TO service_role;
GRANT ALL ON user_client_assignments     TO service_role;
GRANT ALL ON activity_logs               TO service_role;
GRANT ALL ON ai_insights                 TO service_role;
GRANT ALL ON gstr1_returns               TO service_role;
GRANT ALL ON gstr3b_returns              TO service_role;
GRANT ALL ON tds_challans                TO service_role;
GRANT ALL ON tds_returns                 TO service_role;
GRANT ALL ON tds_certificates            TO service_role;
GRANT ALL ON mca_companies               TO service_role;
GRANT ALL ON mca_directors               TO service_role;
GRANT ALL ON fixed_assets                TO service_role;
GRANT ALL ON notifications               TO service_role;
GRANT ALL ON time_entries                TO service_role;
GRANT ALL ON workflows                   TO service_role;
GRANT ALL ON workflow_instances          TO service_role;
GRANT ALL ON workflow_executions         TO service_role;
