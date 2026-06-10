"""
Tests for notification_service.py
Verifies notification creation for task lifecycle events.
"""
import pytest
from services.notification_service import notification_service
from repositories.notifications_repository import notifications_repo


@pytest.fixture
def sample_task():
    """Sample task for testing."""
    return {
        "id": "task-123",
        "firm_id": "firm-1",
        "client_id": "client-1",
        "title": "Q4 Audit",
        "description": "Conduct Q4 financial audit",
        "status": "todo",
        "priority": "high",
        "due_date": "2026-06-20",
        "created_at": "2026-06-10T10:00:00+00:00",
        "updated_at": "2026-06-10T10:00:00+00:00",
    }


@pytest.fixture
def sample_assignee():
    """Sample assignee user."""
    return {
        "id": "user-1",
        "firm_id": "firm-1",
        "email": "assignee@example.com",
        "full_name": "Jane Doe",
        "role": "team_member",
    }


@pytest.fixture
def sample_creator():
    """Sample creator user."""
    return {
        "id": "user-2",
        "firm_id": "firm-1",
        "email": "creator@example.com",
        "full_name": "John Smith",
        "role": "manager",
    }


@pytest.fixture
def sample_manager():
    """Sample manager user."""
    return {
        "id": "user-3",
        "firm_id": "firm-1",
        "email": "manager@example.com",
        "full_name": "Alice Manager",
        "role": "manager",
    }


def test_notify_task_assigned(sample_task, sample_assignee, sample_creator):
    """Test notification creation on task assignment."""
    notification = notification_service.notify_task_assigned(
        task=sample_task,
        assignee_user=sample_assignee,
        created_by_user=sample_creator,
    )

    assert notification is not None
    assert notification["type"] == "task_assigned"
    assert notification["user_id"] == sample_assignee["id"]
    assert notification["severity"] == "info"
    assert "Q4 Audit" in notification["title"]
    assert notification["is_read"] is False
    assert notification["is_archived"] is False


def test_notify_task_reassigned(sample_task, sample_assignee, sample_creator):
    """Test notifications on task reassignment."""
    old_assignee = sample_assignee.copy()
    old_assignee["id"] = "user-old"

    new_assignee = sample_assignee.copy()
    new_assignee["id"] = "user-new"

    notifications = notification_service.notify_task_reassigned(
        task=sample_task,
        old_assignee=old_assignee,
        new_assignee=new_assignee,
        reason="Workload rebalancing",
    )

    assert len(notifications) == 2
    assert notifications[0]["user_id"] == old_assignee["id"]
    assert "reassigned from you" in notifications[0]["title"].lower()
    assert notifications[1]["user_id"] == new_assignee["id"]
    assert "reassigned to you" in notifications[1]["title"].lower()


def test_notify_due_soon(sample_task, sample_assignee):
    """Test notification for tasks due in 3 days."""
    notification = notification_service.notify_due_soon(
        task=sample_task,
        assignee_user=sample_assignee,
    )

    assert notification is not None
    assert notification["type"] == "due_soon"
    assert notification["severity"] == "warning"
    assert "3 days" in notification["title"]
    assert notification["user_id"] == sample_assignee["id"]


def test_notify_overdue(sample_task, sample_assignee, sample_manager):
    """Test notifications for overdue tasks."""
    notifications = notification_service.notify_overdue(
        task=sample_task,
        assignee_user=sample_assignee,
        manager_user=sample_manager,
    )

    assert len(notifications) == 2
    assert notifications[0]["type"] == "overdue"
    assert notifications[0]["severity"] == "critical"
    assert notifications[0]["user_id"] == sample_assignee["id"]
    assert "overdue" in notifications[0]["title"].lower()

    assert notifications[1]["type"] == "overdue"
    assert notifications[1]["severity"] == "critical"
    assert notifications[1]["user_id"] == sample_manager["id"]
    assert "team member" in notifications[1]["title"].lower()


def test_notify_overdue_without_manager(sample_task, sample_assignee):
    """Test overdue notification without a manager."""
    notifications = notification_service.notify_overdue(
        task=sample_task,
        assignee_user=sample_assignee,
        manager_user=None,
    )

    assert len(notifications) == 1
    assert notifications[0]["user_id"] == sample_assignee["id"]


def test_notify_recurring_generated(sample_task, sample_assignee):
    """Test notification for recurring task generation."""
    notification = notification_service.notify_recurring_generated(
        task=sample_task,
        assignee_user=sample_assignee,
        template_name="Monthly GST Filing",
    )

    assert notification is not None
    assert notification["type"] == "recurring_generated"
    assert notification["severity"] == "info"
    assert "Monthly GST Filing" in notification["title"]
    assert notification["user_id"] == sample_assignee["id"]
    assert notification["metadata"]["source"] == "recurring"
