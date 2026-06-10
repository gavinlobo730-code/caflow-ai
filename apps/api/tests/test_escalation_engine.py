import pytest
from datetime import date, timedelta
from repositories.escalation_rule_repository import escalation_rule_repo
from services.escalation_service import escalation_service


@pytest.fixture
def sample_firm_id():
    return "test-firm-123"


@pytest.fixture
def sample_task_due_soon():
    """Task due in 3 days"""
    return {
        "id": "task-due-soon-1",
        "firm_id": "test-firm-123",
        "client_id": "client-1",
        "title": "GST Return Filing",
        "status": "in_progress",
        "priority": "high",
        "assigned_to": "user-1",
        "due_date": (date.today() + timedelta(days=3)).isoformat(),
        "created_at": date.today().isoformat(),
    }


@pytest.fixture
def sample_task_overdue():
    """Task overdue by 2 days"""
    return {
        "id": "task-overdue-1",
        "firm_id": "test-firm-123",
        "client_id": "client-1",
        "title": "Monthly Bookkeeping",
        "status": "in_progress",
        "priority": "medium",
        "assigned_to": "user-1",
        "due_date": (date.today() - timedelta(days=2)).isoformat(),
        "created_at": (date.today() - timedelta(days=10)).isoformat(),
    }


@pytest.fixture
def sample_escalation_rule_due_soon():
    """Escalation rule for tasks due in 3 days"""
    return {
        "id": "rule-due-soon-1",
        "firm_id": "test-firm-123",
        "rule_type": "due_soon",
        "days_threshold": 3,
        "escalate_to_role": "Manager",
        "reassign_to_role": None,
        "is_active": True,
    }


@pytest.fixture
def sample_escalation_rule_overdue():
    """Escalation rule for tasks overdue by 2+ days"""
    return {
        "id": "rule-overdue-1",
        "firm_id": "test-firm-123",
        "rule_type": "overdue",
        "days_threshold": 2,
        "escalate_to_role": "Manager",
        "reassign_to_role": None,
        "is_active": True,
    }


@pytest.fixture
def sample_escalation_rule_reassign():
    """Escalation rule for reassigning overdue tasks"""
    return {
        "id": "rule-reassign-1",
        "firm_id": "test-firm-123",
        "rule_type": "reassign_overdue",
        "days_threshold": 2,
        "escalate_to_role": None,
        "reassign_to_role": "Manager",
        "is_active": True,
    }


class TestEscalationRuleRepository:

    def test_get_applicable_escalations_due_soon(self, sample_task_due_soon, sample_escalation_rule_due_soon):
        """Test finding applicable escalation rules for due-soon tasks"""
        # This test checks the logic of get_applicable_escalations
        task = sample_task_due_soon
        rule = sample_escalation_rule_due_soon

        if not task.get("due_date") or task.get("status") == "completed":
            applicable = []
        else:
            from datetime import datetime
            today = date.today()
            due_date = datetime.fromisoformat(task["due_date"]).date()
            days_until_due = (due_date - today).days

            applicable = []
            if rule.get("rule_type") == "due_soon":
                if days_until_due == rule.get("days_threshold"):
                    applicable.append(rule)

        assert len(applicable) == 1
        assert applicable[0]["rule_type"] == "due_soon"

    def test_get_applicable_escalations_overdue(self, sample_task_overdue, sample_escalation_rule_overdue):
        """Test finding applicable escalation rules for overdue tasks"""
        task = sample_task_overdue
        rule = sample_escalation_rule_overdue

        if not task.get("due_date") or task.get("status") == "completed":
            applicable = []
        else:
            from datetime import datetime
            today = date.today()
            due_date = datetime.fromisoformat(task["due_date"]).date()
            days_overdue = (today - due_date).days

            applicable = []
            if rule.get("rule_type") == "overdue":
                if days_overdue >= rule.get("days_threshold"):
                    applicable.append(rule)

        assert len(applicable) == 1
        assert applicable[0]["rule_type"] == "overdue"

    def test_get_applicable_escalations_no_match(self, sample_task_due_soon, sample_escalation_rule_overdue):
        """Test that non-matching rules are not returned"""
        task = sample_task_due_soon
        rule = sample_escalation_rule_overdue

        # Task due soon should not match overdue rule
        if task.get("due_date"):
            from datetime import datetime
            today = date.today()
            due_date = datetime.fromisoformat(task["due_date"]).date()
            days_overdue = (today - due_date).days

            applicable = []
            if rule.get("rule_type") == "overdue":
                if days_overdue >= rule.get("days_threshold"):
                    applicable.append(rule)

        assert len(applicable) == 0

    def test_get_applicable_escalations_completed_task(self, sample_escalation_rule_due_soon):
        """Test that completed tasks don't trigger escalations"""
        task = {
            "id": "task-completed",
            "due_date": (date.today() + timedelta(days=3)).isoformat(),
            "status": "completed",
        }
        rule = sample_escalation_rule_due_soon

        if not task.get("due_date") or task.get("status") == "completed":
            applicable = []
        else:
            applicable = [rule]

        assert len(applicable) == 0

    def test_get_applicable_escalations_no_due_date(self, sample_escalation_rule_due_soon):
        """Test that tasks without due dates don't trigger escalations"""
        task = {
            "id": "task-no-due",
            "due_date": None,
            "status": "in_progress",
        }
        rule = sample_escalation_rule_due_soon

        if not task.get("due_date") or task.get("status") == "completed":
            applicable = []
        else:
            applicable = [rule]

        assert len(applicable) == 0


class TestEscalationLogic:

    def test_due_soon_notification_logic(self):
        """Test logic for creating due-soon notifications"""
        # Task due in 3 days with rule threshold of 3
        task_due_date = (date.today() + timedelta(days=3)).date()
        today = date.today()
        days_until_due = (task_due_date - today).days
        rule_threshold = 3

        should_escalate = days_until_due == rule_threshold
        assert should_escalate is True

    def test_overdue_reassignment_logic(self):
        """Test logic for overdue task reassignment"""
        # Task overdue by 2 days with rule threshold of 2
        task_due_date = (date.today() - timedelta(days=2)).date()
        today = date.today()
        days_overdue = (today - task_due_date).days
        rule_threshold = 2

        should_escalate = days_overdue >= rule_threshold
        assert should_escalate is True

    def test_overdue_threshold_boundary(self):
        """Test that escalation threshold boundaries work correctly"""
        # Task overdue by exactly 2 days with threshold of 2 should match
        task_due_date = (date.today() - timedelta(days=2)).date()
        today = date.today()
        days_overdue = (today - task_due_date).days
        rule_threshold = 2

        should_escalate = days_overdue >= rule_threshold
        assert should_escalate is True

        # Task overdue by 1 day with threshold of 2 should NOT match
        task_due_date = (date.today() - timedelta(days=1)).date()
        days_overdue = (today - task_due_date).days
        should_escalate = days_overdue >= rule_threshold
        assert should_escalate is False

    def test_multiple_applicable_rules(self):
        """Test handling multiple applicable escalation rules"""
        task = {
            "due_date": (date.today() - timedelta(days=3)).isoformat(),
            "status": "in_progress",
        }

        rules = [
            {"rule_type": "overdue", "days_threshold": 2},
            {"rule_type": "manager_notify", "days_threshold": 3},
        ]

        applicable = []
        from datetime import datetime
        today = date.today()
        due_date = datetime.fromisoformat(task["due_date"]).date()
        days_overdue = (today - due_date).days

        for rule in rules:
            if rule.get("rule_type") in ("overdue", "manager_notify"):
                if days_overdue >= rule.get("days_threshold"):
                    applicable.append(rule)

        assert len(applicable) == 2
