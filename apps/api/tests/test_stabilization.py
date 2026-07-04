"""
Stabilization tests — verifies every router fixed in the post-PR-46 sweep:

1. tasks router  — uses task_repo, persists across calls, firm-scoped
2. team router   — uses user_repo + task_repo, never returns mock members
3. insights router (legacy /api/insights) — delegates to ai_insights_repo
4. reminders router — uses reminders_repo, firm-scoped
5. client workspace — compliance/docs/tasks/insights from real repos
6. task domain service dashboard summary — uses real repos, firm-scoped
"""
import pytest
from unittest.mock import patch, MagicMock

FIRM_A = "firm-001"
FIRM_B = "firm-999"
USER_A = {"auth_user_id": "dev-user", "firm_id": FIRM_A, "role": "Partner"}
USER_B = {"auth_user_id": "dev-user2", "firm_id": FIRM_B, "role": "Partner"}


# ─── 1. Tasks router ─────────────────────────────────────────────────────────

class TestTasksRouter:
    def test_list_tasks_calls_task_repo_not_mock_store(self):
        from routers.tasks import list_tasks
        with patch("routers.tasks.task_repo") as mock_repo, \
             patch("routers.tasks.client_repo") as mock_client_repo:
            mock_repo.find_all.return_value = []
            mock_client_repo.find_all.return_value = []
            result = list_tasks(current_user=USER_A)
        assert result["success"] is True
        mock_repo.find_all.assert_called_once_with(
            firm_id=FIRM_A, client_id=None, status=None, assigned_to=None, priority=None
        )

    def test_create_task_persists_via_repo(self):
        from routers.tasks import create_task, TaskCreate
        with patch("routers.tasks.task_repo") as mock_repo, \
             patch("routers.tasks.client_repo") as mock_client_repo:
            mock_client_repo.find_by_id.return_value = {"id": "c-001", "firm_id": FIRM_A}
            mock_repo.create.return_value = {
                "id": "new-task-id", "title": "File GSTR-1",
                "client_id": "c-001", "firm_id": FIRM_A, "status": "todo",
            }
            body = TaskCreate(client_id="c-001", title="File GSTR-1")
            result = create_task(body=body, current_user=USER_A)
        assert result["success"] is True
        mock_repo.create.assert_called_once()

    def test_list_tasks_kanban_returns_kanban_key(self):
        from routers.tasks import list_tasks
        with patch("routers.tasks.task_repo") as mock_repo, \
             patch("routers.tasks.client_repo") as mock_client_repo:
            mock_repo.find_all.return_value = []
            mock_client_repo.find_all.return_value = []
            result = list_tasks(kanban=True, current_user=USER_A)
        assert "kanban" in result["data"]

    def test_update_task_uses_repo(self):
        from routers.tasks import update_task, TaskUpdate
        existing = {"id": "tk-1", "firm_id": FIRM_A, "status": "todo", "title": "Old"}
        with patch("routers.tasks.task_repo") as mock_repo:
            mock_repo.find_by_id.return_value = existing
            mock_repo.update.return_value = {**existing, "status": "in_progress"}
            result = update_task(task_id="tk-1", body=TaskUpdate(status="in_progress"), current_user=USER_A)
        assert result["success"] is True
        mock_repo.update.assert_called_once()

    def test_update_task_cross_firm_returns_404(self):
        from routers.tasks import update_task, TaskUpdate
        from fastapi import HTTPException
        firm_b_task = {"id": "tk-b", "firm_id": FIRM_B, "status": "todo"}
        with patch("routers.tasks.task_repo") as mock_repo:
            mock_repo.find_by_id.return_value = firm_b_task
            with pytest.raises(HTTPException) as exc:
                update_task(task_id="tk-b", body=TaskUpdate(title="hack"), current_user=USER_A)
        assert exc.value.status_code == 404


# ─── 2. Team router ──────────────────────────────────────────────────────────

class TestTeamRouter:
    def test_team_uses_user_repo_not_mock(self):
        from routers.team import list_team
        with patch("routers.team.user_repo") as mock_user_repo, \
             patch("routers.team.task_repo") as mock_task_repo:
            mock_user_repo.find_all.return_value = [
                {"id": "u-1", "full_name": "Real CA", "role": "Partner", "firm_id": FIRM_A}
            ]
            mock_task_repo.find_all.return_value = []
            result = list_team(current_user=USER_A)
        assert result["success"] is True
        mock_user_repo.find_all.assert_called_once_with(firm_id=FIRM_A)

    def test_team_scoped_to_firm(self):
        from routers.team import list_team
        with patch("routers.team.user_repo") as mock_user_repo, \
             patch("routers.team.task_repo") as mock_task_repo:
            mock_user_repo.find_all.return_value = []
            mock_task_repo.find_all.return_value = []
            list_team(current_user=USER_B)
        mock_user_repo.find_all.assert_called_with(firm_id=FIRM_B)


# ─── 3. Legacy insights router ───────────────────────────────────────────────

class TestLegacyInsightsRouter:
    def test_list_insights_delegates_to_ai_insights_repo(self):
        from routers.insights import list_insights
        with patch("routers.insights.ai_insights_repo") as mock_repo:
            mock_repo.find_all.return_value = []
            result = list_insights(current_user=USER_A)
        assert result["success"] is True
        mock_repo.find_all.assert_called_once_with(firm_id=FIRM_A, client_id=None, status=None)

    def test_update_status_persists_via_repo(self):
        from routers.insights import update_insight_status
        with patch("routers.insights.ai_insights_repo") as mock_repo:
            mock_repo.update_status.return_value = {"id": "ins-1", "status": "acknowledged"}
            result = update_insight_status(insight_id="ins-1", new_status="acknowledged", current_user=USER_A)
        assert result["success"] is True
        mock_repo.update_status.assert_called_once_with("ins-1", "acknowledged", firm_id=FIRM_A)

    def test_invalid_status_rejected(self):
        from routers.insights import update_insight_status
        result = update_insight_status(insight_id="ins-1", new_status="deleted", current_user=USER_A)
        assert result["success"] is False

    def test_insight_not_found_returns_failure(self):
        from routers.insights import update_insight_status
        with patch("routers.insights.ai_insights_repo") as mock_repo:
            mock_repo.update_status.return_value = None
            result = update_insight_status(insight_id="bad-id", new_status="acknowledged", current_user=USER_A)
        assert result["success"] is False


# ─── 4. Reminders router ─────────────────────────────────────────────────────

class TestRemindersRouter:
    def test_list_reminders_uses_repo(self):
        from routers.reminders import list_reminders
        with patch("routers.reminders.reminders_repo") as mock_repo:
            mock_repo.find_all.return_value = []
            result = list_reminders(current_user=USER_A)
        assert result["success"] is True
        mock_repo.find_all.assert_called_once_with(firm_id=FIRM_A, client_id=None, status=None)

    def test_create_reminder_persists_firm_id(self):
        from routers.reminders import create_reminder_endpoint, ReminderCreate
        with patch("routers.reminders.reminders_repo") as mock_repo, \
             patch("routers.reminders.create_reminder") as mock_svc:
            mock_svc.return_value = {"id": "r-new", "status": "pending"}
            mock_repo.create.return_value = {"id": "r-new", "firm_id": FIRM_A, "status": "pending"}
            body = ReminderCreate(client_id="c-001", reminder_type="email", scheduled_for="2026-07-01T10:00:00Z")
            result = create_reminder_endpoint(body=body, current_user=USER_A)
        assert result["success"] is True
        call_kwargs = mock_repo.create.call_args[0][0]
        assert call_kwargs["firm_id"] == FIRM_A

    def test_mark_sent_cross_firm_returns_404(self):
        from routers.reminders import mark_reminder_sent
        from fastapi import HTTPException
        firm_b_reminder = {"id": "r-b", "firm_id": FIRM_B, "status": "pending"}
        with patch("routers.reminders.reminders_repo") as mock_repo:
            mock_repo.find_by_id.return_value = firm_b_reminder
            with pytest.raises(HTTPException) as exc:
                mark_reminder_sent(reminder_id="r-b", current_user=USER_A)
        assert exc.value.status_code == 404


# ─── 5. Client workspace ─────────────────────────────────────────────────────

class TestClientWorkspace:
    CLIENT = {"id": "c-001", "firm_id": FIRM_A, "client_name": "Test Co", "status": "active"}

    def test_workspace_compliance_tasks_from_repo(self):
        from routers.clients import get_client_workspace
        with patch("routers.clients.client_repo") as mock_client, \
             patch("routers.clients.compliance_records_repo") as mock_crecords, \
             patch("routers.clients.document_repo") as mock_docs, \
             patch("routers.clients.task_repo") as mock_tasks, \
             patch("routers.clients.ai_insights_repo") as mock_insights:
            mock_client.find_by_id.return_value = self.CLIENT
            mock_crecords.find_all.return_value = [
                {"id": "cr-1", "status": "Not Started", "due_date": "2026-07-11", "compliance_type": "GST"}
            ]
            mock_docs.find_all.return_value = []
            mock_tasks.find_all.return_value = []
            mock_insights.find_all.return_value = []
            result = get_client_workspace(client_id="c-001", current_user=USER_A)
        assert result["success"] is True
        assert len(result["data"]["compliance_tasks"]) == 1
        mock_crecords.find_all.assert_called_once_with(firm_id=FIRM_A, client_id="c-001")

    def test_workspace_tenant_isolation(self):
        from routers.clients import get_client_workspace
        from fastapi import HTTPException
        with patch("routers.clients.client_repo") as mock_client:
            mock_client.find_by_id.return_value = self.CLIENT  # belongs to FIRM_A
            with pytest.raises(HTTPException) as exc:
                get_client_workspace(client_id="c-001", current_user=USER_B)
        assert exc.value.status_code == 404

    def test_workspace_documents_from_repo(self):
        from routers.clients import get_client_workspace
        with patch("routers.clients.client_repo") as mock_client, \
             patch("routers.clients.compliance_records_repo") as mock_crecords, \
             patch("routers.clients.document_repo") as mock_docs, \
             patch("routers.clients.task_repo") as mock_tasks, \
             patch("routers.clients.ai_insights_repo") as mock_insights:
            mock_client.find_by_id.return_value = self.CLIENT
            mock_crecords.find_all.return_value = []
            mock_docs.find_all.return_value = [{"id": "doc-1", "file_name": "invoice.pdf"}]
            mock_tasks.find_all.return_value = []
            mock_insights.find_all.return_value = []
            result = get_client_workspace(client_id="c-001", current_user=USER_A)
        assert result["data"]["summary"]["document_count"] == 1
        mock_docs.find_all.assert_called_once_with(firm_id=FIRM_A, client_id="c-001")


# ─── 6. Dashboard summary ────────────────────────────────────────────────────

class TestDashboardSummary:
    def test_summary_uses_client_repo_not_mock(self):
        from domain.task_service import task_domain_service
        with patch("domain.task_service.client_repo") as mock_clients, \
             patch("domain.task_service.task_repo") as mock_tasks, \
             patch("domain.compliance_record_service.compliance_record_service") as mock_records:
            mock_clients.find_all.return_value = [
                {"id": "c-1", "status": "active"}, {"id": "c-2", "status": "archived"}
            ]
            mock_tasks.find_all.return_value = []
            mock_tasks.find_overdue.return_value = []
            mock_records.list_records.return_value = []
            mock_records.score_from_records.return_value = (80, [])
            result = task_domain_service.get_dashboard_summary(firm_id=FIRM_A)
        assert result["active_clients"] == 1
        mock_clients.find_all.assert_called_with(firm_id=FIRM_A)

    def test_summary_firm_scoped(self):
        from domain.task_service import task_domain_service
        with patch("domain.task_service.client_repo") as mock_clients, \
             patch("domain.task_service.task_repo") as mock_tasks, \
             patch("domain.compliance_record_service.compliance_record_service") as mock_records:
            mock_clients.find_all.return_value = []
            mock_tasks.find_all.return_value = []
            mock_tasks.find_overdue.return_value = []
            mock_records.list_records.return_value = []
            task_domain_service.get_dashboard_summary(firm_id=FIRM_B)
        mock_clients.find_all.assert_called_with(firm_id=FIRM_B)
