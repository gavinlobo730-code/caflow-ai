"""
Tests for Phase 10 Workflow Automation Engine.
"""
import pytest
from datetime import datetime
from domain.workflow_engine_v2 import WorkflowEngineV2


@pytest.fixture
def engine():
    return WorkflowEngineV2()


@pytest.fixture
def repo():
    from repositories.workflow_repository import workflow_repo
    return workflow_repo


# ── Condition evaluation ────────────────────────────────────────────────────────

class TestConditionEvaluation:
    def test_numeric_greater_than_true(self, engine):
        rule = {"field": "score", "operator": ">", "value": "40", "value_type": "number"}
        assert engine._eval_rule(rule, {"score": 50}) is True

    def test_numeric_greater_than_false(self, engine):
        rule = {"field": "score", "operator": ">", "value": "40", "value_type": "number"}
        assert engine._eval_rule(rule, {"score": 30}) is False

    def test_numeric_less_than_true(self, engine):
        rule = {"field": "health_score", "operator": "<", "value": "60", "value_type": "number"}
        assert engine._eval_rule(rule, {"health_score": 55}) is True

    def test_numeric_equals(self, engine):
        rule = {"field": "days_remaining", "operator": "=", "value": "7", "value_type": "number"}
        assert engine._eval_rule(rule, {"days_remaining": 7}) is True

    def test_numeric_gte(self, engine):
        rule = {"field": "amount", "operator": ">=", "value": "1000", "value_type": "number"}
        assert engine._eval_rule(rule, {"amount": 1000}) is True
        assert engine._eval_rule(rule, {"amount": 999}) is False

    def test_string_contains_true(self, engine):
        rule = {"field": "name", "operator": "contains", "value": "Ltd", "value_type": "string"}
        assert engine._eval_rule(rule, {"name": "Acme Ltd"}) is True

    def test_string_contains_false(self, engine):
        rule = {"field": "name", "operator": "contains", "value": "LLC", "value_type": "string"}
        assert engine._eval_rule(rule, {"name": "Acme Ltd"}) is False

    def test_string_equals(self, engine):
        rule = {"field": "status", "operator": "equals", "value": "active", "value_type": "string"}
        assert engine._eval_rule(rule, {"status": "active"}) is True

    def test_string_starts_with(self, engine):
        rule = {"field": "code", "operator": "starts_with", "value": "GST", "value_type": "string"}
        assert engine._eval_rule(rule, {"code": "GSTR-3B"}) is True
        assert engine._eval_rule(rule, {"code": "TDS-26Q"}) is False

    def test_and_group_all_true(self, engine):
        group = {
            "logic": "AND",
            "rules": [
                {"field": "score", "operator": "<", "value": "60", "value_type": "number"},
                {"field": "status", "operator": "equals", "value": "active", "value_type": "string"},
            ],
            "groups": [],
        }
        assert engine._evaluate_conditions(group, {"score": 45, "status": "active"}) is True

    def test_and_group_one_false(self, engine):
        group = {
            "logic": "AND",
            "rules": [
                {"field": "score", "operator": "<", "value": "60", "value_type": "number"},
                {"field": "status", "operator": "equals", "value": "active", "value_type": "string"},
            ],
            "groups": [],
        }
        assert engine._evaluate_conditions(group, {"score": 75, "status": "active"}) is False

    def test_or_group_one_true(self, engine):
        group = {
            "logic": "OR",
            "rules": [
                {"field": "score", "operator": "<", "value": "40", "value_type": "number"},
                {"field": "status", "operator": "equals", "value": "overdue", "value_type": "string"},
            ],
            "groups": [],
        }
        assert engine._evaluate_conditions(group, {"score": 75, "status": "overdue"}) is True

    def test_empty_conditions_always_true(self, engine):
        assert engine._evaluate_conditions({}, {"score": 99}) is True
        assert engine._evaluate_conditions(None, {}) is True  # type: ignore


# ── Trigger config matching ────────────────────────────────────────────────────

class TestTriggerConfig:
    def test_days_before_match(self, engine):
        assert engine._matches_trigger_config({"days_before": 7}, {"days_remaining": 5}) is True
        assert engine._matches_trigger_config({"days_before": 7}, {"days_remaining": 10}) is False

    def test_threshold_match(self, engine):
        assert engine._matches_trigger_config({"threshold": 40}, {"score": 35}) is True
        assert engine._matches_trigger_config({"threshold": 40}, {"score": 50}) is False

    def test_severity_match(self, engine):
        assert engine._matches_trigger_config({"severity": "critical"}, {"severity": "critical"}) is True
        assert engine._matches_trigger_config({"severity": "critical"}, {"severity": "high"}) is False

    def test_empty_config_always_matches(self, engine):
        assert engine._matches_trigger_config({}, {"anything": "here"}) is True


# ── Repository ────────────────────────────────────────────────────────────────

class TestWorkflowRepository:
    def test_list_templates_returns_system_templates(self, repo):
        templates = repo.list_templates("any-firm-id")
        assert len(templates) > 0
        assert all(t.get("is_system") or t["firm_id"] in ("any-firm-id", "system") for t in templates)

    def test_create_and_get_template(self, repo):
        data = {
            "name": "Test Workflow",
            "description": "Test description",
            "category": "gst",
            "trigger_type": "gst_due",
            "trigger_config": {"days_before": 5},
            "conditions": {},
            "is_active": True,
            "steps": [],
        }
        created = repo.create_template("firm-test", data)
        assert created["id"] is not None
        assert created["name"] == "Test Workflow"
        assert created["firm_id"] == "firm-test"

        fetched = repo.get_template("firm-test", created["id"])
        assert fetched is not None
        assert fetched["id"] == created["id"]

    def test_create_approval(self, repo):
        approval = repo.create_approval(
            "firm-001", "wfi-001", "step-001",
            "Test Approval", "Partner", "Approve this", "Please review", {}
        )
        assert approval["id"] is not None
        assert approval["status"] == "pending"

    def test_respond_approval(self, repo):
        approval = repo.create_approval(
            "firm-001", "wfi-001", "step-002",
            "Test Approval", "Manager", "Approve", "Please review", {}
        )
        responded = repo.respond_approval("firm-001", approval["id"], "approved", "user-001", "Looks good")
        assert responded["status"] == "approved"
        assert responded["response_notes"] == "Looks good"

    def test_log_failure(self, repo):
        failure = repo.log_failure("firm-001", "wfi-001", "step-001", "ActionFailed", "Task creation failed")
        assert failure["id"] is not None
        assert failure["resolved"] is False

    def test_resolve_failure(self, repo):
        failure = repo.log_failure("firm-001", "wfi-001", None, "NetworkError", "Timeout")
        resolved = repo.resolve_failure("firm-001", failure["id"], "user-001")
        assert resolved["resolved"] is True
        assert resolved["resolved_by"] == "user-001"

    def test_analytics_structure(self, repo):
        analytics = repo.get_analytics("firm-001")
        for a in analytics:
            assert "template_id" in a
            assert "success_rate" in a
            assert isinstance(a["success_rate"], int)
            assert 0 <= a["success_rate"] <= 100


# ── Action execution (unit) ───────────────────────────────────────────────────

class TestActionExecution:
    def test_create_task_action(self, engine):
        step = {"step_type": "action", "id": "s-1", "name": "Create Task", "config": {
            "action_type": "create_task",
            "params": {"title": "File GSTR-3B", "priority": "high"},
        }, "next_step_id": None}
        instance = {"id": "i-1", "trigger_data": {}, "template_id": "t-1"}
        result, next_id = engine._execute_step(step, instance, {}, "firm-001")
        assert "task_id" in result
        assert result["title"] == "File GSTR-3B"
        assert next_id is None

    def test_send_notification_action(self, engine):
        step = {"step_type": "action", "id": "s-2", "name": "Notify", "config": {
            "action_type": "send_notification",
            "params": {"title": "Filing Due", "severity": "high"},
        }, "next_step_id": None}
        instance = {"id": "i-1", "trigger_data": {}, "template_id": "t-1"}
        result, _ = engine._execute_step(step, instance, {}, "firm-001")
        assert "notification_id" in result

    def test_delay_action(self, engine):
        step = {"step_type": "delay", "id": "s-3", "name": "Wait", "config": {"delay_hours": 24},
                "next_step_id": "s-4"}
        instance = {"id": "i-1", "trigger_data": {}, "template_id": "t-1"}
        result, next_id = engine._execute_step(step, instance, {}, "firm-001")
        assert result["delayed_hours"] == 24
        assert next_id == "s-4"

    def test_branch_true_path(self, engine):
        step = {
            "step_type": "branch", "id": "s-5", "name": "Branch",
            "config": {"condition": {"logic": "AND", "rules": [
                {"field": "score", "operator": "<", "value": "60", "value_type": "number"}
            ], "groups": []}},
            "true_branch_step_id": "s-yes",
            "false_branch_step_id": "s-no",
        }
        instance = {"id": "i-1", "trigger_data": {"score": 45}, "template_id": "t-1"}
        result, next_id = engine._execute_step(step, instance, {}, "firm-001")
        assert next_id == "s-yes"
        assert result["branch_taken"] == "true"

    def test_branch_false_path(self, engine):
        step = {
            "step_type": "branch", "id": "s-5", "name": "Branch",
            "config": {"condition": {"logic": "AND", "rules": [
                {"field": "score", "operator": "<", "value": "60", "value_type": "number"}
            ], "groups": []}},
            "true_branch_step_id": "s-yes",
            "false_branch_step_id": "s-no",
        }
        instance = {"id": "i-1", "trigger_data": {"score": 80}, "template_id": "t-1"}
        result, next_id = engine._execute_step(step, instance, {}, "firm-001")
        assert next_id == "s-no"
        assert result["branch_taken"] == "false"
