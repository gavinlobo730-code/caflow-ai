"""
Tenant isolation unit tests.
Verifies that cross-firm access is blocked at the router layer for:
  - GET /api/clients/{client_id}          (Critical fix)
  - GET /api/compliance/tasks             (High fix)
  - GET /api/compliance/calendar          (High fix)
  - GET /api/documents/{doc_id}/download-url (Medium fix)

Tests operate directly on router handler functions, bypassing HTTP
transport and JWT verification (which are tested separately in test_rbac.py).
"""
import pytest
from fastapi import HTTPException
from unittest.mock import patch, MagicMock


# ── Shared fixtures ───────────────────────────────────────────────────────────

FIRM_A = "firm-aaa"
FIRM_B = "firm-bbb"

USER_FIRM_A = {"auth_user_id": "u1", "firm_id": FIRM_A, "role": "Partner"}
USER_FIRM_B = {"auth_user_id": "u2", "firm_id": FIRM_B, "role": "Partner"}


# ── Client workspace tenant isolation ─────────────────────────────────────────

class TestClientWorkspaceTenantIsolation:
    """GET /api/clients/{client_id} must return 404 for cross-firm access."""

    def _call(self, client_id: str, current_user: dict, mock_client: dict | None):
        from routers.clients import get_client_workspace
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = mock_client
            return get_client_workspace(client_id=client_id, current_user=current_user)

    def test_own_firm_client_returns_workspace(self):
        """A user can access a client that belongs to their firm."""
        client = {"id": "c-001", "firm_id": FIRM_A, "client_name": "Sharma Enterprises"}
        result = self._call("c-001", USER_FIRM_A, client)
        assert result["success"] is True
        assert result["data"]["profile"]["id"] == "c-001"

    def test_cross_firm_client_returns_404(self):
        """A user from Firm A cannot access a client belonging to Firm B."""
        client_firm_b = {"id": "c-999", "firm_id": FIRM_B, "client_name": "Secret Corp"}
        with pytest.raises(HTTPException) as exc_info:
            self._call("c-999", USER_FIRM_A, client_firm_b)
        assert exc_info.value.status_code == 404
        # Must not leak the real reason — attacker learns nothing
        assert exc_info.value.detail == "Client not found"

    def test_nonexistent_client_returns_404(self):
        """A missing client ID returns 404."""
        with pytest.raises(HTTPException) as exc_info:
            self._call("c-does-not-exist", USER_FIRM_A, None)
        assert exc_info.value.status_code == 404

    def test_client_with_no_firm_id_accessible(self):
        """Mock clients with no firm_id (legacy / seed data) are accessible — no crash."""
        client_no_firm = {"id": "c-legacy", "client_name": "Legacy Corp"}
        # Should not raise — firm_id is None so ownership check is skipped
        result = self._call("c-legacy", USER_FIRM_A, client_no_firm)
        assert result["success"] is True


# ── Compliance tenant isolation ───────────────────────────────────────────────

class TestComplianceTenantIsolation:
    """Compliance endpoints must only return data for the requesting firm."""

    TASKS_MIXED = [
        {"id": "t1", "client_id": "c1", "firm_id": FIRM_A, "status": "pending", "due_date": "2026-07-11", "compliance_type": "GSTR1"},
        {"id": "t2", "client_id": "c2", "firm_id": FIRM_B, "status": "pending", "due_date": "2026-07-11", "compliance_type": "GSTR1"},
        {"id": "t3", "client_id": "c3", "firm_id": None,   "status": "filed",   "due_date": "2026-06-30", "compliance_type": "GSTR9"},
    ]

    def _firm_a_tasks(self):
        return [t for t in self.TASKS_MIXED if t.get("firm_id") == FIRM_A or t.get("firm_id") is None]

    def _firm_b_tasks(self):
        return [t for t in self.TASKS_MIXED if t.get("firm_id") == FIRM_B or t.get("firm_id") is None]

    def test_list_tasks_only_returns_own_firm_and_legacy(self):
        from routers.compliance import list_compliance_tasks
        with patch("routers.compliance.compliance_repo") as mock_repo:
            mock_repo.find_all.return_value = self._firm_a_tasks()
            result = list_compliance_tasks(client_id=None, status=None, current_user=USER_FIRM_A)
        ids = [t["id"] for t in result["data"]["tasks"]]
        assert "t1" in ids     # own firm ✓
        assert "t3" in ids     # no firm_id (legacy) ✓
        assert "t2" not in ids # Firm B — must be excluded ✗
        # Verify repo was called with the correct firm_id
        mock_repo.find_all.assert_called_once_with(firm_id=FIRM_A, client_id=None, status=None)

    def test_list_tasks_firm_b_excluded_from_firm_a(self):
        from routers.compliance import list_compliance_tasks
        with patch("routers.compliance.compliance_repo") as mock_repo:
            mock_repo.find_all.return_value = self._firm_b_tasks()
            result = list_compliance_tasks(client_id=None, status=None, current_user=USER_FIRM_B)
        ids = [t["id"] for t in result["data"]["tasks"]]
        assert "t2" in ids
        assert "t1" not in ids
        mock_repo.find_all.assert_called_once_with(firm_id=FIRM_B, client_id=None, status=None)

    def test_calendar_only_returns_own_firm(self):
        from routers.compliance import compliance_calendar
        with patch("routers.compliance.compliance_repo") as mock_repo, \
             patch("routers.compliance.client_repo") as mock_client_repo:
            mock_repo.find_all.return_value = self._firm_a_tasks()
            mock_client_repo.find_all.return_value = []
            result = compliance_calendar(current_user=USER_FIRM_A)
        ids = [e["id"] for e in result["data"]["events"]]
        assert "t1" in ids
        assert "t2" not in ids

    def test_status_filter_still_applies_within_firm(self):
        from routers.compliance import list_compliance_tasks
        filed_only = [t for t in self._firm_a_tasks() if t["status"] == "filed"]
        with patch("routers.compliance.compliance_repo") as mock_repo:
            mock_repo.find_all.return_value = filed_only
            result = list_compliance_tasks(client_id=None, status="filed", current_user=USER_FIRM_A)
        ids = [t["id"] for t in result["data"]["tasks"]]
        assert "t3" in ids
        assert "t1" not in ids  # pending, filtered out by the repo call
        mock_repo.find_all.assert_called_once_with(firm_id=FIRM_A, client_id=None, status="filed")


# ── Document download URL tenant isolation ────────────────────────────────────

class TestDocumentDownloadTenantIsolation:
    """GET /api/documents/{doc_id}/download-url must reject cross-firm and null firm_id."""

    def _call(self, doc_id: str, current_user: dict, mock_doc: dict):
        from routers.documents import get_download_url
        with patch("routers.documents.document_repo") as mock_repo, \
             patch("routers.documents._USE_MOCK", True):
            mock_repo.get_or_raise.return_value = mock_doc
            return get_download_url(doc_id=doc_id, current_user=current_user)

    def test_own_firm_document_returns_url(self):
        doc = {"id": "d1", "firm_id": FIRM_A, "storage_path": "firm-aaa/c1/form16/file.pdf"}
        result = self._call("d1", USER_FIRM_A, doc)
        assert result["success"] is True

    def test_cross_firm_document_returns_404(self):
        """A document belonging to Firm B must not be accessible by Firm A."""
        doc = {"id": "d2", "firm_id": FIRM_B, "storage_path": "firm-bbb/c2/form16/secret.pdf"}
        with pytest.raises(HTTPException) as exc_info:
            self._call("d2", USER_FIRM_A, doc)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Document not found"

    def test_null_firm_id_document_rejected(self):
        """A document with firm_id=None must be rejected — no NULL bypass allowed."""
        doc = {"id": "d3", "firm_id": None, "storage_path": "unknown/file.pdf"}
        with pytest.raises(HTTPException) as exc_info:
            self._call("d3", USER_FIRM_A, doc)
        assert exc_info.value.status_code == 404

    def test_missing_firm_id_field_rejected(self):
        """A document dict with no firm_id key at all must also be rejected."""
        doc = {"id": "d4", "storage_path": "unknown/file.pdf"}  # no firm_id key
        with pytest.raises(HTTPException) as exc_info:
            self._call("d4", USER_FIRM_A, doc)
        assert exc_info.value.status_code == 404


# ── Task tenant isolation ─────────────────────────────────────────────────────

class TestTaskTenantIsolation:
    """GET /api/tasks and PATCH /api/tasks/{id} must be scoped to the requesting firm."""

    TASKS_MIXED = [
        {"id": "tk1", "client_id": "c1", "firm_id": FIRM_A, "title": "File GSTR-1", "status": "todo", "priority": "high"},
        {"id": "tk2", "client_id": "c2", "firm_id": FIRM_B, "title": "Firm B task",  "status": "todo", "priority": "low"},
        {"id": "tk3", "client_id": "c3", "firm_id": None,   "title": "Legacy task",  "status": "todo", "priority": "medium"},
    ]

    def test_list_tasks_only_returns_own_firm_and_legacy(self):
        from routers.tasks import list_tasks
        with patch("routers.tasks.task_repo") as mock_repo, \
             patch("routers.tasks.client_repo") as mock_client_repo:
            mock_repo.find_all.return_value = [
                t for t in self.TASKS_MIXED
                if t.get("firm_id") == FIRM_A or t.get("firm_id") is None
            ]
            mock_client_repo.find_all.return_value = []
            result = list_tasks(client_id=None, status=None, assigned_to=None,
                                priority=None, kanban=False, current_user=USER_FIRM_A)
        ids = [t["id"] for t in result["data"]["tasks"]]
        assert "tk1" in ids      # own firm ✓
        assert "tk3" in ids      # legacy (no firm_id) ✓
        assert "tk2" not in ids  # Firm B — excluded ✗

    def test_list_tasks_firm_b_excludes_firm_a(self):
        from routers.tasks import list_tasks
        with patch("routers.tasks.task_repo") as mock_repo, \
             patch("routers.tasks.client_repo") as mock_client_repo:
            mock_repo.find_all.return_value = [
                t for t in self.TASKS_MIXED
                if t.get("firm_id") == FIRM_B or t.get("firm_id") is None
            ]
            mock_client_repo.find_all.return_value = []
            result = list_tasks(client_id=None, status=None, assigned_to=None,
                                priority=None, kanban=False, current_user=USER_FIRM_B)
        ids = [t["id"] for t in result["data"]["tasks"]]
        assert "tk2" in ids
        assert "tk1" not in ids

    def test_update_cross_firm_task_returns_404(self):
        from routers.tasks import update_task, TaskUpdate
        # task tk2 belongs to FIRM_B; requesting user is FIRM_A → expect 404
        with patch("routers.tasks.task_repo") as mock_repo:
            mock_repo.find_by_id.return_value = self.TASKS_MIXED[1]  # tk2, firm_id=FIRM_B
            body = TaskUpdate(status="in_progress")
            with pytest.raises(HTTPException) as exc_info:
                update_task(task_id="tk2", body=body, current_user=USER_FIRM_A)
        assert exc_info.value.status_code == 404


# ── Compliance records tenant isolation ───────────────────────────────────────

class TestComplianceRecordsTenantIsolation:
    """GET /api/compliance-records and sub-resources must be firm-scoped."""

    RECORDS_MIXED = [
        {"id": "cr-a1", "firm_id": FIRM_A, "client_id": "c1", "compliance_type": "GST",
         "status": "In Progress", "due_date": "2026-07-11", "priority": "high",
         "period_label": "Jun 2026", "period_start": "2026-06-01", "period_end": "2026-06-30",
         "filed_date": None, "acknowledgement_no": None, "notes": None, "assigned_to": None,
         "created_at": "2026-06-01", "updated_at": "2026-06-01"},
        {"id": "cr-b1", "firm_id": FIRM_B, "client_id": "c2", "compliance_type": "GST",
         "status": "Filed", "due_date": "2026-07-11", "priority": "low",
         "period_label": "Jun 2026", "period_start": "2026-06-01", "period_end": "2026-06-30",
         "filed_date": "2026-07-10", "acknowledgement_no": "ARN123", "notes": None, "assigned_to": None,
         "created_at": "2026-06-01", "updated_at": "2026-07-10"},
    ]

    def test_list_records_scoped_to_firm(self):
        from routers.compliance_records import list_compliance_records
        with patch("routers.compliance_records.compliance_record_service") as mock_svc:
            mock_svc.list_records.return_value = [self.RECORDS_MIXED[0]]
            result = list_compliance_records(client_id=None, status=None, compliance_type=None, current_user=USER_FIRM_A)
        mock_svc.list_records.assert_called_once_with(firm_id=FIRM_A, client_id=None, status=None, compliance_type=None)
        assert result["data"][0]["id"] == "cr-a1"

    def test_get_cross_firm_record_returns_404(self):
        from routers.compliance_records import get_compliance_record
        from core.exceptions import NotFoundError
        with patch("routers.compliance_records.compliance_record_service") as mock_svc:
            mock_svc.get_record.side_effect = NotFoundError("ComplianceRecord", "cr-b1")
            with pytest.raises(HTTPException) as exc_info:
                get_compliance_record(record_id="cr-b1", current_user=USER_FIRM_A)
        assert exc_info.value.status_code == 404

    def test_create_record_uses_firm_from_user_not_body(self):
        from routers.compliance_records import create_compliance_record
        created = {**self.RECORDS_MIXED[0], "id": "cr-new"}
        with patch("routers.compliance_records.compliance_record_service") as mock_svc:
            mock_svc.create_record.return_value = created
            body = {"client_id": "c1", "compliance_type": "GST", "due_date": "2026-07-11", "firm_id": FIRM_B}
            create_compliance_record(data=body, current_user=USER_FIRM_A)
        # firm_id must be USER_FIRM_A["firm_id"], regardless of what was in body
        call_kwargs = mock_svc.create_record.call_args
        assert call_kwargs.kwargs["firm_id"] == FIRM_A
