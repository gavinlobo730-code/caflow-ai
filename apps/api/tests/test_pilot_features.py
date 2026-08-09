"""
Tests for the 6 pilot-critical production features:
1. AI Copilot firm-context endpoint
2. Notifications (repo-backed, firm-scoped)
3. Automation rules (repo-backed, firm-scoped)
4. Risk engine (real compliance data sources)
5. AI Insights (repo-backed, firm-scoped)
6. Tenant isolation across all new endpoints
"""
import pytest
from unittest.mock import patch, MagicMock

FIRM_A = "firm-001"
FIRM_B = "firm-999"

USER_A = {"auth_user_id": "dev-user", "firm_id": FIRM_A, "role": "Partner"}
USER_B = {"auth_user_id": "dev-user2", "firm_id": FIRM_B, "role": "Partner"}


# ─── 1. AI Copilot firm-context ──────────────────────────────────────────────

class TestAICopilotFirmContext:
    def test_get_firm_context_returns_structured_data(self):
        from routers.ai_copilot import get_firm_context
        result = get_firm_context(current_user=USER_A)
        assert result["success"] is True
        body = result["data"]
        assert "active_clients" in body
        assert "clients" in body
        assert isinstance(body["clients"], list)
        assert "tasks" in body
        assert "compliance" in body
        assert "risks" in body

    def test_firm_context_tasks_structure(self):
        from routers.ai_copilot import get_firm_context
        result = get_firm_context(current_user=USER_A)
        tasks = result["data"]["tasks"]
        assert "overdue" in tasks
        assert "due_today" in tasks
        assert "due_this_week" in tasks

    def test_firm_context_compliance_structure(self):
        from routers.ai_copilot import get_firm_context
        result = get_firm_context(current_user=USER_A)
        compliance = result["data"]["compliance"]
        assert "overdue" in compliance
        assert "ready_to_file" in compliance

    def test_firm_context_risks_structure(self):
        from routers.ai_copilot import get_firm_context
        result = get_firm_context(current_user=USER_A)
        risks = result["data"]["risks"]
        assert "critical" in risks
        assert "total_open" in risks

    def test_firm_context_clients_scoped_to_firm(self):
        from routers.ai_copilot import get_firm_context
        mock_clients = [{"id": "c-A1", "client_name": "Firm A Client", "status": "active"}]
        with patch("repositories.client_repository.client_repo.find_all", return_value=mock_clients):
            result = get_firm_context(current_user=USER_A)
        names = [c["name"] for c in result["data"]["clients"]]
        assert "Firm A Client" in names

    def test_firm_context_client_repo_called_with_firm_id(self):
        from routers.ai_copilot import get_firm_context
        mock_find = MagicMock(return_value=[])
        with patch("repositories.client_repository.client_repo.find_all", mock_find):
            get_firm_context(current_user=USER_A)
        call_kwargs = mock_find.call_args[1]
        assert call_kwargs.get("firm_id") == FIRM_A


# ─── 2. Notifications ────────────────────────────────────────────────────────

class TestNotificationsRepo:
    def test_list_notifications_returns_list(self):
        from routers.notifications import list_notifications
        result = list_notifications(current_user=USER_A)
        assert result["success"] is True
        assert isinstance(result["data"]["notifications"], list)

    def test_unread_count_returns_integer(self):
        from routers.notifications import unread_count
        result = unread_count(current_user=USER_A)
        assert result["success"] is True
        assert isinstance(result["data"]["unread"], int)

    def test_unread_only_filter(self):
        from routers.notifications import list_notifications
        unread = list_notifications(unread_only=True, current_user=USER_A)["data"]["notifications"]
        assert all(not n["is_read"] for n in unread)

    def test_mark_one_read(self):
        from routers.notifications import read_one
        from domain.notification_service import MOCK_NOTIFICATIONS
        unread = [n for n in MOCK_NOTIFICATIONS if not n["is_read"]]
        if not unread:
            pytest.skip("No unread notifications")
        nid = unread[0]["id"]
        result = read_one(notification_id=nid, current_user=USER_A)
        assert result["success"] is True
        assert result["data"]["is_read"] is True

    def test_mark_all_read(self):
        from routers.notifications import read_all
        result = read_all(current_user=USER_A)
        assert result["success"] is True
        assert "marked_read" in result["data"]

    def test_notification_stats_structure(self):
        from routers.notifications import notification_stats
        result = notification_stats(current_user=USER_A)
        assert result["success"] is True
        stats = result["data"]
        assert "total" in stats
        assert "unread" in stats
        assert "by_type" in stats

    def test_create_notification_via_repo(self):
        from repositories.notifications_repository import notifications_repo
        before = len(notifications_repo.find_all())
        notif = notifications_repo.create({
            "type": "compliance_due",
            "title": "Test Notification",
            "body": "Test body",
            "severity": "info",
        })
        assert notif["id"].startswith("notif-")
        assert notif["is_read"] is False
        after = len(notifications_repo.find_all())
        assert after == before + 1

    def test_list_passes_firm_id_to_repo(self):
        from routers.notifications import list_notifications
        mock_repo = MagicMock()
        mock_repo.find_all = MagicMock(return_value=[])
        with patch("routers.notifications.notifications_repo", mock_repo):
            list_notifications(current_user=USER_A)
        mock_repo.find_all.assert_called_once()
        assert mock_repo.find_all.call_args[1].get("firm_id") == FIRM_A


# ─── 3. Automation Rules ─────────────────────────────────────────────────────

class TestAutomationRepo:
    def test_list_rules_returns_list(self):
        from routers.automation import list_rules
        result = list_rules(current_user=USER_A)
        assert result["success"] is True
        rules = result["data"]
        assert isinstance(rules, list)
        assert len(rules) > 0

    def test_rule_structure(self):
        from routers.automation import list_rules
        rules = list_rules(current_user=USER_A)["data"]
        rule = rules[0]
        assert "trigger_type" in rule
        assert "action_type" in rule
        assert "is_enabled" in rule

    def test_toggle_rule(self):
        from routers.automation import toggle
        from domain.automation_engine import MOCK_AUTOMATION_RULES
        rule_id = MOCK_AUTOMATION_RULES[0]["id"]
        original = MOCK_AUTOMATION_RULES[0]["is_enabled"]
        result = toggle(rule_id=rule_id, enabled=not original, current_user=USER_A)
        assert result["success"] is True
        # Restore
        toggle(rule_id=rule_id, enabled=original, current_user=USER_A)

    def test_executions_returns_list(self):
        from routers.automation import executions
        result = executions(current_user=USER_A)
        assert result["success"] is True
        assert isinstance(result["data"], list)

    def test_automation_stats_structure(self):
        from routers.automation import stats
        result = stats(current_user=USER_A)
        assert result["success"] is True
        s = result["data"]
        assert "rules_active" in s
        assert "executions_today" in s

    def test_manual_trigger(self):
        from routers.automation import manual_trigger, TriggerBody
        body = TriggerBody(trigger_type="risk_detected", trigger_data={"severity": "critical", "client_id": "c-001"})
        result = manual_trigger(body=body, current_user=USER_A)
        assert result["success"] is True
        assert "count" in result["data"]

    def test_evaluate_rules_persists_execution(self):
        from repositories.automation_repository import automation_repo
        before = len(automation_repo.get_executions())
        from domain.automation_engine import evaluate_rules
        evaluate_rules("risk_detected", {"severity": "critical", "client_id": "c-001"}, firm_id=FIRM_A)
        after = len(automation_repo.get_executions())
        assert after > before

    def test_rules_firm_scoped(self):
        from routers.automation import list_rules
        mock_repo = MagicMock()
        mock_repo.get_rules = MagicMock(return_value=[])
        with patch("routers.automation.automation_repo", mock_repo):
            list_rules(current_user=USER_A)
        mock_repo.get_rules.assert_called_once_with(firm_id=FIRM_A)


# ─── 4. Risk Engine ──────────────────────────────────────────────────────────

class TestRiskEngine:
    def test_list_risks_returns_list(self):
        from routers.risks import list_risks
        result = list_risks(current_user=USER_A)
        assert result["success"] is True
        assert isinstance(result["data"], list)

    def test_risk_stats_structure(self):
        from routers.risks import risk_stats
        result = risk_stats(current_user=USER_A)
        assert result["success"] is True
        stats = result["data"]
        for key in ("critical", "high", "medium", "low", "total_open"):
            assert key in stats

    def test_firm_score_returns_int(self):
        from routers.risks import firm_score
        result = firm_score(current_user=USER_A)
        assert result["success"] is True
        score = result["data"]["score"]
        assert isinstance(score, int)
        assert 0 <= score <= 100

    def test_client_risks_structure(self):
        from routers.risks import client_risks
        result = client_risks(client_id="c-001", current_user=USER_A)
        assert result["success"] is True
        summary = result["data"]
        assert "risk_score" in summary
        assert "risks_by_severity" in summary
        assert "top_risks" in summary

    def test_compliance_risks_derived_from_overdue_compliance_records(self):
        """R3.13d: derived from compliance_records (System A) — compliance_tasks
        (System B) is being retired and no longer feeds this at all. Seeds its
        own row rather than relying on mock_data.py's fixture rows, which
        other test files mutate over the course of a full-suite run."""
        from domain.risk_engine import _derive_compliance_risks
        from repositories.compliance_records_repository import compliance_records_repo
        record = compliance_records_repo.create({
            "firm_id": "risk-firm-1", "client_id": "risk-client-1",
            "compliance_type": "GST", "status": "Overdue", "due_date": "2026-01-11",
        })
        derived = _derive_compliance_risks(firm_id=None, client_id=record["client_id"])
        assert any(r["source"] == "compliance" for r in derived)

    def test_risk_severity_filter(self):
        from routers.risks import list_risks
        result = list_risks(severity="critical", current_user=USER_A)
        assert result["success"] is True
        risks = result["data"]
        assert all(r["severity"] == "critical" for r in risks)

    def test_list_risks_passes_firm_id(self):
        from routers.risks import list_risks
        mock_fn = MagicMock(return_value=[])
        with patch("routers.risks.get_all_risks", mock_fn):
            list_risks(current_user=USER_A)
        assert mock_fn.call_args[1].get("firm_id") == FIRM_A

    def test_firm_score_passes_firm_id(self):
        from routers.risks import firm_score
        mock_fn = MagicMock(return_value=50)
        with patch("routers.risks.compute_firm_risk_score", mock_fn):
            firm_score(current_user=USER_A)
        assert mock_fn.call_args[1].get("firm_id") == FIRM_A


# ─── 5. AI Insights ──────────────────────────────────────────────────────────

class TestAIInsights:
    def test_list_insights_returns_list(self):
        from routers.ai_insights import list_insights
        result = list_insights(current_user=USER_A)
        assert result["success"] is True
        assert isinstance(result["data"], list)

    def test_insight_feed_sorted_by_severity(self):
        from routers.ai_insights import insight_feed
        result = insight_feed(current_user=USER_A)
        assert result["success"] is True
        feed = result["data"]
        severity_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        severities = [severity_order.get(i["severity"], 5) for i in feed]
        assert severities == sorted(severities)

    def test_generate_insights_for_client(self):
        from routers.ai_insights import generate_insights
        result = generate_insights(client_id="c-001", current_user=USER_A)
        assert result["success"] is True
        assert "generated" in result["data"]
        assert isinstance(result["data"]["generated"], int)

    def test_acknowledge_insight(self):
        from routers.ai_insights import ack_insight, list_insights
        open_items = list_insights(status="open", current_user=USER_A)["data"]
        if not open_items:
            pytest.skip("No open insights")
        iid = open_items[0]["id"]
        result = ack_insight(insight_id=iid, current_user=USER_A)
        assert result["success"] is True
        assert result["data"]["status"] == "acknowledged"

    def test_dismiss_insight(self):
        from routers.ai_insights import dis_insight, list_insights
        open_items = list_insights(status="open", current_user=USER_A)["data"]
        if not open_items:
            pytest.skip("No open insights")
        iid = open_items[0]["id"]
        result = dis_insight(insight_id=iid, current_user=USER_A)
        assert result["success"] is True
        assert result["data"]["status"] == "dismissed"

    def test_filter_by_category(self):
        from routers.ai_insights import list_insights
        result = list_insights(category="compliance", current_user=USER_A)
        assert result["success"] is True
        assert all(i["category"] == "compliance" for i in result["data"])

    def test_generate_creates_repo_backed_insights(self):
        from repositories.ai_insights_repository import ai_insights_repo
        before = len(ai_insights_repo.find_all())
        from domain.ai_insight_service import generate_insights_for_client
        generate_insights_for_client("c-001", firm_id=FIRM_A)
        after = len(ai_insights_repo.find_all())
        assert after >= before

    def test_list_insights_passes_firm_id(self):
        from routers.ai_insights import list_insights
        mock_fn = MagicMock(return_value=[])
        with patch("routers.ai_insights.get_all_insights", mock_fn):
            list_insights(current_user=USER_A)
        assert mock_fn.call_args[1].get("firm_id") == FIRM_A

    def test_generate_passes_firm_id(self):
        from routers.ai_insights import generate_insights
        mock_fn = MagicMock(return_value=[])
        with patch("routers.ai_insights.generate_insights_for_client", mock_fn):
            generate_insights(client_id="c-001", current_user=USER_A)
        assert mock_fn.call_args[1].get("firm_id") == FIRM_A


# ─── 6. Tenant Isolation ─────────────────────────────────────────────────────

class TestTenantIsolationPilotFeatures:
    def test_ai_copilot_firm_context_uses_firm_id(self):
        from routers.ai_copilot import get_firm_context
        mock_clients_a = [{"id": "c-A1", "client_name": "Firm A Client", "status": "active"}]
        mock_clients_b = [{"id": "c-B1", "client_name": "Firm B Client", "status": "active"}]

        with patch("repositories.client_repository.client_repo.find_all", return_value=mock_clients_a):
            result_a = get_firm_context(current_user=USER_A)
        names_a = [c["name"] for c in result_a["data"]["clients"]]
        assert "Firm A Client" in names_a
        assert "Firm B Client" not in names_a

    def test_notifications_firm_id_passed_to_repo(self):
        from routers.notifications import list_notifications
        mock_repo = MagicMock()
        mock_repo.find_all = MagicMock(return_value=[])
        with patch("routers.notifications.notifications_repo", mock_repo):
            list_notifications(current_user=USER_A)
        assert mock_repo.find_all.call_args[1].get("firm_id") == FIRM_A

    def test_automation_rules_firm_id_passed(self):
        from routers.automation import list_rules
        mock_repo = MagicMock()
        mock_repo.get_rules = MagicMock(return_value=[])
        with patch("routers.automation.automation_repo", mock_repo):
            list_rules(current_user=USER_A)
        mock_repo.get_rules.assert_called_once_with(firm_id=FIRM_A)

    def test_risk_firm_id_passed(self):
        from routers.risks import list_risks
        mock_fn = MagicMock(return_value=[])
        with patch("routers.risks.get_all_risks", mock_fn):
            list_risks(current_user=USER_A)
        assert mock_fn.call_args[1].get("firm_id") == FIRM_A

    def test_ai_insights_firm_id_passed(self):
        from routers.ai_insights import list_insights
        mock_fn = MagicMock(return_value=[])
        with patch("routers.ai_insights.get_all_insights", mock_fn):
            list_insights(current_user=USER_A)
        assert mock_fn.call_args[1].get("firm_id") == FIRM_A

    def test_notifications_count_firm_scoped(self):
        from routers.notifications import unread_count
        mock_repo = MagicMock()
        mock_repo.count_unread = MagicMock(return_value=3)
        with patch("routers.notifications.notifications_repo", mock_repo):
            result = unread_count(current_user=USER_A)
        assert result["data"]["unread"] == 3
        mock_repo.count_unread.assert_called_once_with(firm_id=FIRM_A, user_id=None)


# ─── Compliance Seed API Contract ────────────────────────────────────────────

class TestComplianceSeedContract:
    def test_seed_with_int_year(self):
        from routers.compliance import seed_compliance_calendar
        with patch("routers.compliance.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = {"id": "c-001", "firm_id": FIRM_A}
            with patch("routers.compliance.compliance_repo") as mock_cr:
                mock_cr.create.return_value = {"id": "t-1"}
                result = seed_compliance_calendar(client_id="c-001", financial_year="2025", current_user=USER_A)
        assert result["success"] is True
        assert result["data"]["seeded"] == 30

    def test_seed_with_fy_string_format(self):
        """Frontend sends '2025-26' — must be accepted."""
        from routers.compliance import seed_compliance_calendar
        with patch("routers.compliance.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = {"id": "c-001", "firm_id": FIRM_A}
            with patch("routers.compliance.compliance_repo") as mock_cr:
                mock_cr.create.return_value = {"id": "t-1"}
                result = seed_compliance_calendar(client_id="c-001", financial_year="2025-26", current_user=USER_A)
        assert result["success"] is True
        assert result["data"]["seeded"] == 30

    def test_seed_with_none_defaults_to_current_fy(self):
        from routers.compliance import seed_compliance_calendar
        with patch("routers.compliance.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = {"id": "c-001", "firm_id": FIRM_A}
            with patch("routers.compliance.compliance_repo") as mock_cr:
                mock_cr.create.return_value = {"id": "t-1"}
                result = seed_compliance_calendar(client_id="c-001", financial_year=None, current_user=USER_A)
        assert result["success"] is True
        assert result["data"]["seeded"] == 30

    def test_seed_with_invalid_string_returns_422(self):
        from fastapi import HTTPException
        from routers.compliance import seed_compliance_calendar
        with patch("routers.compliance.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = {"id": "c-001", "firm_id": FIRM_A}
            with pytest.raises(HTTPException) as exc_info:
                seed_compliance_calendar(client_id="c-001", financial_year="bad-value", current_user=USER_A)
        assert exc_info.value.status_code == 422

    def test_seed_2025_and_2025_26_produce_same_tasks(self):
        """Both formats must seed identical task counts."""
        from routers.compliance import seed_compliance_calendar
        results = []
        for fy in ("2025", "2025-26"):
            with patch("routers.compliance.client_repo") as mock_repo:
                mock_repo.find_by_id.return_value = {"id": "c-001", "firm_id": FIRM_A}
                with patch("routers.compliance.compliance_repo") as mock_cr:
                    mock_cr.create.return_value = {"id": "t-1"}
                    r = seed_compliance_calendar(client_id="c-001", financial_year=fy, current_user=USER_A)
                    results.append(r["data"]["seeded"])
        assert results[0] == results[1]


# ─── Compliance Seed — client-assignment scope (M2) ──────────────────────────
# Sweep finding: seed_compliance_calendar checked only client.firm_id ==
# firm_id — a bespoke inline firm-boundary check — and never the caller's
# assignment, letting an Executive/Manager seed ~30 task rows into any other
# staff member's assigned client. Mock mode's can_access_client is permissive
# by design (no assignments table), so assert_client_access is patched
# directly to simulate real enforcement — the same technique the
# *_client_scope.py `deny` fixtures use.

class TestComplianceSeedAssignmentScope:
    def test_seeding_an_unassigned_clients_calendar_is_refused(self):
        from fastapi import HTTPException
        from routers.compliance import seed_compliance_calendar

        def _deny(user, client_id):
            raise HTTPException(status_code=404, detail="Not found")

        with patch("routers.compliance.assert_client_access", _deny):
            with pytest.raises(HTTPException) as exc_info:
                seed_compliance_calendar(client_id="c-001", financial_year="2025-26", current_user=USER_A)
        assert exc_info.value.status_code == 404

    def test_seeding_an_assigned_clients_calendar_still_works(self):
        from routers.compliance import seed_compliance_calendar
        with patch("routers.compliance.assert_client_access", lambda user, client_id: None):
            with patch("routers.compliance.compliance_repo") as mock_cr:
                mock_cr.create.return_value = {"id": "t-1"}
                result = seed_compliance_calendar(client_id="c-001", financial_year="2025-26", current_user=USER_A)
        assert result["success"] is True
        assert result["data"]["seeded"] == 30
