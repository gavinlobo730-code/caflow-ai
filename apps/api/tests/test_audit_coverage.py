"""
H10 — audit_log coverage regression tests.

These assert that the immutable audit trail (services.audit_service.log_event) is
actually written for the high-value mutations that previously only went through the
no-op activity_service.log_activity stub or a separate timeline store.

Pattern mirrors the sibling router unit tests (test_lead_creation.py,
test_engagement_letters.py): the router functions are called directly in mock mode
with their dependencies patched. log_event is patched WHERE IT IS USED (imported
into each router's module namespace), then we assert on the (entity_type, action)
positional pair via call_args_list so the assertions stay tolerant of the optional
kwargs (actor_id, actor_email, old_data, new_data).
"""
import asyncio
from unittest.mock import patch, MagicMock

FIRM_ID = "firm-audit-0001"

USER_MANAGER = {
    "auth_user_id": "u-mgr-1",
    "firm_id": FIRM_ID,
    "role": "Manager",
    "email": "manager@firm.test",
}


def _entity_action_pairs(mock_log_event):
    """Extract the (entity_type, action) positional pairs from every log_event call.

    Signature: log_event(firm_id, entity_type, entity_id, action, ...).
    entity_type is positional arg 1, action is positional arg 3.
    """
    pairs = []
    for call in mock_log_event.call_args_list:
        args = call.args
        if len(args) >= 4:
            pairs.append((args[1], args[3]))
    return pairs


# ─── Tasks ────────────────────────────────────────────────────────────────────

class TestTaskAuditCoverage:
    """create_task / update_task write audit_log records."""

    def _make_task_create(self, **overrides):
        from routers.tasks import TaskCreate
        data = {
            "client_id": "client-1",
            "title": "File GSTR-3B",
            "status": "todo",
            "priority": "medium",
        }
        data.update(overrides)
        return TaskCreate(**data)

    def test_create_task_logs_create(self):
        from routers.tasks import create_task
        body = self._make_task_create()

        fake_repo = MagicMock()
        fake_repo.create.return_value = {
            "id": "task-100", "title": body.title, "status": "todo", "priority": "medium",
        }

        with patch("routers.tasks.log_event") as mock_log, \
             patch("routers.tasks.assert_client_access"), \
             patch("routers.tasks.client_repo") as mock_client_repo, \
             patch("routers.tasks.task_repo", fake_repo):
            mock_client_repo.find_by_id.return_value = {"id": "client-1", "firm_id": FIRM_ID}
            create_task(body=body, current_user=USER_MANAGER)

        assert ("task", "create") in _entity_action_pairs(mock_log)

    def test_create_task_with_assignee_logs_create_and_assign(self):
        from routers.tasks import create_task
        body = self._make_task_create(assigned_to="user-assignee-1")

        fake_repo = MagicMock()
        fake_repo.create.return_value = {
            "id": "task-101", "title": body.title, "status": "todo", "priority": "medium",
        }
        fake_user_repo = MagicMock()
        fake_user_repo.find_by_id.return_value = {"id": "user-assignee-1", "firm_id": FIRM_ID}

        with patch("routers.tasks.log_event") as mock_log, \
             patch("routers.tasks.assert_client_access"), \
             patch("routers.tasks.client_repo") as mock_client_repo, \
             patch("routers.tasks.task_repo", fake_repo), \
             patch("repositories.user_repository.user_repo", fake_user_repo), \
             patch("services.notification_service.notification_service"):
            mock_client_repo.find_by_id.return_value = {"id": "client-1", "firm_id": FIRM_ID}
            create_task(body=body, current_user=USER_MANAGER)

        pairs = _entity_action_pairs(mock_log)
        assert ("task", "create") in pairs
        assert ("task", "assign") in pairs

    def test_complete_task_logs_complete(self):
        from routers.tasks import update_task, TaskUpdate

        fake_repo = MagicMock()
        # Old task is in_progress so the todo→completed transition is valid.
        fake_repo.find_by_id.return_value = {
            "id": "task-200", "firm_id": FIRM_ID, "status": "in_progress",
            "assigned_to": None, "priority": "medium",
        }
        fake_repo.update.return_value = {
            "id": "task-200", "firm_id": FIRM_ID, "status": "completed",
        }

        with patch("routers.tasks.log_event") as mock_log, \
             patch("routers.tasks.task_repo", fake_repo):
            update_task(
                task_id="task-200",
                body=TaskUpdate(status="completed"),
                current_user=USER_MANAGER,
            )

        assert ("task", "complete") in _entity_action_pairs(mock_log)


# ─── Leads ────────────────────────────────────────────────────────────────────

class TestLeadAuditCoverage:
    """create_lead writes an audit_log record."""

    def test_create_lead_logs_create(self):
        from routers.lifecycle import create_lead, LeadIn
        body = LeadIn(company_name="Patel Industries", source="referral", stage="Lead")

        with patch("routers.lifecycle.log_event") as mock_log, \
             patch("routers.lifecycle._db", return_value=None), \
             patch("routers.lifecycle.timeline_service"):
            result = create_lead(body, current_user=USER_MANAGER)

        assert result["success"] is True
        assert ("lead", "create") in _entity_action_pairs(mock_log)


# ─── Documents ────────────────────────────────────────────────────────────────

class _FakeUpload:
    """Minimal stand-in for fastapi UploadFile in mock mode."""

    def __init__(self, filename="pan_card.pdf", content_type="application/pdf"):
        self.filename = filename
        self.content_type = content_type

    async def read(self):
        return b"%PDF-1.4 fake bytes"


class TestDocumentAuditCoverage:
    """upload_document writes an audit_log record in mock mode."""

    def test_upload_document_logs_upload(self):
        from routers.documents import upload_document

        fake_doc_repo = MagicMock()
        fake_doc_repo.create.return_value = {"id": "doc-300"}

        with patch("routers.documents.log_event") as mock_log, \
             patch("routers.documents._USE_MOCK", True), \
             patch("routers.documents.assert_partner_for_internal_id"), \
             patch("routers.documents.assert_client_access"), \
             patch("routers.documents.document_repo", fake_doc_repo):
            asyncio.run(upload_document(
                file=_FakeUpload(),
                document_type="PAN",
                client_id="client-1",
                current_user=USER_MANAGER,
            ))

        assert ("document", "upload") in _entity_action_pairs(mock_log)
