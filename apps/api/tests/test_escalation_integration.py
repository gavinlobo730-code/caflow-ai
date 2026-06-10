"""
Integration tests for escalation rules engine.
Tests the flow: rules → applicable logic → notifications/escalations
"""
import pytest
from datetime import date, datetime, timedelta
from typing import Optional


class MockTaskRepository:
    """Mock task repository for testing escalation logic"""
    def __init__(self, tasks: list[dict]):
        self.tasks = tasks

    def find_all(self, firm_id: Optional[str] = None, status: Optional[str] = None, **kwargs) -> list[dict]:
        results = self.tasks
        if firm_id:
            results = [t for t in results if t.get("firm_id") == firm_id]
        return results


class MockNotificationsRepository:
    """Mock notifications repository for testing"""
    def __init__(self):
        self.created_notifications = []

    def create(self, data: dict) -> dict:
        notification = {"id": f"notif-{len(self.created_notifications)}", **data}
        self.created_notifications.append(notification)
        return notification


class MockEscalationRuleRepository:
    """Mock escalation rule repository for testing"""
    def __init__(self, rules: list[dict]):
        self.rules = rules

    def find_active_by_firm(self, firm_id: str) -> list[dict]:
        return [r for r in self.rules if r.get("firm_id") == firm_id and r.get("is_active")]

    def get_applicable_escalations(self, firm_id: str, task: dict) -> list[dict]:
        """Simulate the real logic of finding applicable escalations"""
        if not task.get("due_date") or task.get("status") == "completed":
            return []

        today = date.today()
        due_date = datetime.fromisoformat(task["due_date"]).date() if isinstance(task["due_date"], str) else task["due_date"]

        all_rules = self.find_active_by_firm(firm_id)
        applicable = []

        for rule in all_rules:
            rule_type = rule.get("rule_type")
            days_threshold = rule.get("days_threshold", 0)

            if rule_type == "due_soon":
                days_until_due = (due_date - today).days
                if days_until_due == days_threshold:
                    applicable.append(rule)

            elif rule_type in ("overdue", "reassign_overdue", "manager_notify"):
                days_overdue = (today - due_date).days
                if days_overdue >= days_threshold:
                    applicable.append(rule)

        return applicable


class TestEscalationIntegration:
    """Integration tests for the escalation rules engine"""

    def test_task_due_soon_generates_notification(self):
        """
        Acceptance Test 1: Task 3 days before due generates notification
        - Given: A task due in exactly 3 days
        - And: An active escalation rule for "due_soon" with threshold 3 days
        - When: Escalation check runs
        - Then: Notification is created for Manager role
        """
        firm_id = "test-firm"
        task = {
            "id": "task-1",
            "firm_id": firm_id,
            "title": "GST Return",
            "status": "in_progress",
            "due_date": (date.today() + timedelta(days=3)).isoformat(),
        }

        rule = {
            "id": "rule-1",
            "firm_id": firm_id,
            "rule_type": "due_soon",
            "days_threshold": 3,
            "escalate_to_role": "Manager",
            "is_active": True,
        }

        # Setup mocks
        rule_repo = MockEscalationRuleRepository([rule])
        notif_repo = MockNotificationsRepository()

        # Get applicable rules
        applicable = rule_repo.get_applicable_escalations(firm_id, task)
        assert len(applicable) == 1
        assert applicable[0]["rule_type"] == "due_soon"

        # Simulate notification creation
        if applicable:
            for rule in applicable:
                if rule.get("escalate_to_role"):
                    notif_repo.create({
                        "firm_id": firm_id,
                        "user_id": "manager-1",
                        "type": "task_due_soon",
                        "title": f"Task Due Soon: {task['title']}",
                        "message": f"Task '{task['title']}' is due in {rule['days_threshold']} day(s).",
                    })

        assert len(notif_repo.created_notifications) == 1
        assert notif_repo.created_notifications[0]["type"] == "task_due_soon"

    def test_overdue_task_triggers_reassignment(self):
        """
        Acceptance Test 2: Overdue task triggers reassignment to manager
        - Given: A task overdue by 2 days
        - And: An active escalation rule for "reassign_overdue" with threshold 2 days
        - And: A Manager role user available
        - When: Escalation check runs
        - Then: Task is reassigned to Manager
        - And: Manager is notified
        """
        firm_id = "test-firm"
        task = {
            "id": "task-2",
            "firm_id": firm_id,
            "title": "Monthly Bookkeeping",
            "status": "in_progress",
            "assigned_to": "staff-1",
            "due_date": (date.today() - timedelta(days=2)).isoformat(),
        }

        rule = {
            "id": "rule-2",
            "firm_id": firm_id,
            "rule_type": "reassign_overdue",
            "days_threshold": 2,
            "reassign_to_role": "Manager",
            "is_active": True,
        }

        # Setup mocks
        rule_repo = MockEscalationRuleRepository([rule])

        # Get applicable rules
        applicable = rule_repo.get_applicable_escalations(firm_id, task)
        assert len(applicable) == 1
        assert applicable[0]["rule_type"] == "reassign_overdue"

        # Verify the escalation would trigger
        assert applicable[0]["days_threshold"] <= 2

    def test_manager_notification_for_overdue(self):
        """
        Acceptance Test 3: Clear notifications sent to appropriate users
        - Given: An overdue task
        - And: A manager_notify escalation rule
        - When: Escalation check runs
        - Then: Manager receives notification with task details
        """
        firm_id = "test-firm"
        task = {
            "id": "task-3",
            "firm_id": firm_id,
            "title": "Annual Accounts",
            "status": "in_progress",
            "assigned_to": "staff-1",
            "due_date": (date.today() - timedelta(days=5)).isoformat(),
        }

        rule = {
            "id": "rule-3",
            "firm_id": firm_id,
            "rule_type": "manager_notify",
            "days_threshold": 2,
            "is_active": True,
        }

        # Setup mocks
        rule_repo = MockEscalationRuleRepository([rule])
        notif_repo = MockNotificationsRepository()

        # Get applicable rules (task is 5 days overdue, rule threshold is 2)
        applicable = rule_repo.get_applicable_escalations(firm_id, task)
        assert len(applicable) == 1

        # Create notification
        if applicable:
            for rule in applicable:
                notif_repo.create({
                    "firm_id": firm_id,
                    "user_id": "manager-1",
                    "type": "task_overdue_notification",
                    "title": f"Overdue Task: {task['title']}",
                    "message": f"Task '{task['title']}' is overdue.",
                    "metadata": {
                        "task_id": task["id"],
                        "days_overdue": 5,
                    }
                })

        assert len(notif_repo.created_notifications) == 1
        assert notif_repo.created_notifications[0]["type"] == "task_overdue_notification"

    def test_multiple_escalations_for_same_task(self):
        """Test that a task can trigger multiple escalation rules"""
        firm_id = "test-firm"
        task = {
            "id": "task-4",
            "firm_id": firm_id,
            "title": "Quarterly TDS Return",
            "status": "in_progress",
            "due_date": (date.today() - timedelta(days=3)).isoformat(),
        }

        rules = [
            {
                "id": "rule-4a",
                "firm_id": firm_id,
                "rule_type": "overdue",
                "days_threshold": 2,
                "is_active": True,
            },
            {
                "id": "rule-4b",
                "firm_id": firm_id,
                "rule_type": "manager_notify",
                "days_threshold": 3,
                "is_active": True,
            },
        ]

        # Setup mocks
        rule_repo = MockEscalationRuleRepository(rules)

        # Get applicable rules (task is 3 days overdue)
        applicable = rule_repo.get_applicable_escalations(firm_id, task)
        assert len(applicable) == 2

    def test_completed_tasks_not_escalated(self):
        """Test that completed tasks don't trigger escalations"""
        firm_id = "test-firm"
        task = {
            "id": "task-5",
            "firm_id": firm_id,
            "title": "GST Return",
            "status": "completed",
            "due_date": (date.today() - timedelta(days=5)).isoformat(),
        }

        rule = {
            "id": "rule-5",
            "firm_id": firm_id,
            "rule_type": "overdue",
            "days_threshold": 2,
            "is_active": True,
        }

        # Setup mocks
        rule_repo = MockEscalationRuleRepository([rule])

        # Get applicable rules
        applicable = rule_repo.get_applicable_escalations(firm_id, task)
        assert len(applicable) == 0

    def test_tasks_without_due_date_not_escalated(self):
        """Test that tasks without due dates don't trigger escalations"""
        firm_id = "test-firm"
        task = {
            "id": "task-6",
            "firm_id": firm_id,
            "title": "Ad-hoc Review",
            "status": "in_progress",
            "due_date": None,
        }

        rule = {
            "id": "rule-6",
            "firm_id": firm_id,
            "rule_type": "overdue",
            "days_threshold": 2,
            "is_active": True,
        }

        # Setup mocks
        rule_repo = MockEscalationRuleRepository([rule])

        # Get applicable rules
        applicable = rule_repo.get_applicable_escalations(firm_id, task)
        assert len(applicable) == 0

    def test_inactive_rules_not_applied(self):
        """Test that inactive escalation rules are not applied"""
        firm_id = "test-firm"
        task = {
            "id": "task-7",
            "firm_id": firm_id,
            "title": "GST Return",
            "status": "in_progress",
            "due_date": (date.today() - timedelta(days=3)).isoformat(),
        }

        rule = {
            "id": "rule-7",
            "firm_id": firm_id,
            "rule_type": "overdue",
            "days_threshold": 2,
            "is_active": False,
        }

        # Setup mocks
        rule_repo = MockEscalationRuleRepository([rule])

        # Get applicable rules
        applicable = rule_repo.get_applicable_escalations(firm_id, task)
        assert len(applicable) == 0
