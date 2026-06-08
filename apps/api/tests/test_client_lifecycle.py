"""
Client lifecycle management tests.
Covers: archive, restore, soft-delete, is_test filtering,
        deletion blockers, and tenant isolation for new endpoints.
"""
import pytest
from fastapi import HTTPException
from unittest.mock import patch, MagicMock

FIRM_A = "firm-aaa"
FIRM_B = "firm-bbb"

USER_PARTNER_A = {"auth_user_id": "u1", "firm_id": FIRM_A, "role": "Partner"}
USER_MANAGER_A = {"auth_user_id": "u2", "firm_id": FIRM_A, "role": "Manager"}

ACTIVE_CLIENT = {
    "id": "c-active", "firm_id": FIRM_A, "client_name": "Active Corp",
    "status": "active", "is_test": False, "deleted_at": None,
}
ARCHIVED_CLIENT = {
    "id": "c-archived", "firm_id": FIRM_A, "client_name": "Old Corp",
    "status": "archived", "is_test": False, "deleted_at": None,
}
TEST_CLIENT = {
    "id": "c-test", "firm_id": FIRM_A, "client_name": "Test Client",
    "status": "active", "is_test": True, "deleted_at": None,
}
DELETED_CLIENT = {
    "id": "c-deleted", "firm_id": FIRM_A, "client_name": "Gone Corp",
    "status": "active", "is_test": False, "deleted_at": "2026-01-01T00:00:00",
}
FIRM_B_CLIENT = {
    "id": "c-firmb", "firm_id": FIRM_B, "client_name": "Other Firm Client",
    "status": "active", "is_test": False, "deleted_at": None,
}


# ── Archive ───────────────────────────────────────────────────────────────────

class TestArchiveClient:

    def test_archive_active_client_succeeds(self):
        from routers.clients import archive_client
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = ACTIVE_CLIENT
            mock_repo.archive.return_value = {**ACTIVE_CLIENT, "status": "archived"}
            result = archive_client(client_id="c-active", current_user=USER_PARTNER_A)
        assert result["data"]["client"]["status"] == "archived"
        mock_repo.archive.assert_called_once_with("c-active")

    def test_archive_already_archived_returns_409(self):
        from routers.clients import archive_client
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = ARCHIVED_CLIENT
            with pytest.raises(HTTPException) as exc_info:
                archive_client(client_id="c-archived", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 409

    def test_archive_missing_client_returns_404(self):
        from routers.clients import archive_client
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                archive_client(client_id="c-missing", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 404

    def test_archive_cross_firm_returns_404(self):
        from routers.clients import archive_client
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = FIRM_B_CLIENT
            with pytest.raises(HTTPException) as exc_info:
                archive_client(client_id="c-firmb", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 404

    def test_manager_can_archive(self):
        from routers.clients import archive_client
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = ACTIVE_CLIENT
            mock_repo.archive.return_value = {**ACTIVE_CLIENT, "status": "archived"}
            result = archive_client(client_id="c-active", current_user=USER_MANAGER_A)
        assert result["data"]["client"]["status"] == "archived"


# ── Restore ───────────────────────────────────────────────────────────────────

class TestRestoreClient:

    def test_restore_archived_client_succeeds(self):
        from routers.clients import restore_client
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = ARCHIVED_CLIENT
            mock_repo.restore.return_value = {**ARCHIVED_CLIENT, "status": "active"}
            result = restore_client(client_id="c-archived", current_user=USER_PARTNER_A)
        assert result["data"]["client"]["status"] == "active"
        mock_repo.restore.assert_called_once_with("c-archived")

    def test_restore_active_client_returns_409(self):
        from routers.clients import restore_client
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = ACTIVE_CLIENT
            with pytest.raises(HTTPException) as exc_info:
                restore_client(client_id="c-active", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 409

    def test_restore_missing_returns_404(self):
        from routers.clients import restore_client
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                restore_client(client_id="c-missing", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 404

    def test_restore_cross_firm_returns_404(self):
        from routers.clients import restore_client
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = FIRM_B_CLIENT
            with pytest.raises(HTTPException) as exc_info:
                restore_client(client_id="c-firmb", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 404


# ── Soft delete ───────────────────────────────────────────────────────────────

class TestDeleteClient:

    def _no_blockers(self):
        """Patch that simulates no open compliance obligations."""
        return patch("routers.clients._check_delete_blockers", return_value=[])

    def test_partner_can_delete_clean_client(self):
        from routers.clients import delete_client
        with patch("routers.clients.client_repo") as mock_repo, self._no_blockers():
            mock_repo.find_by_id.return_value = ACTIVE_CLIENT
            mock_repo.soft_delete.return_value = True
            result = delete_client(client_id="c-active", current_user=USER_PARTNER_A)
        assert result["success"] is True
        mock_repo.soft_delete.assert_called_once_with("c-active")

    def test_delete_blocked_when_open_compliance_obligations(self):
        from routers.clients import delete_client
        with patch("routers.clients.client_repo") as mock_repo, \
             patch("routers.clients._check_delete_blockers", return_value=["2 open compliance tasks: GSTR1, GSTR3B"]):
            mock_repo.find_by_id.return_value = ACTIVE_CLIENT
            with pytest.raises(HTTPException) as exc_info:
                delete_client(client_id="c-active", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 409
        assert "blockers" in exc_info.value.detail
        assert "open compliance" in exc_info.value.detail["blockers"][0]

    def test_delete_missing_client_returns_404(self):
        from routers.clients import delete_client
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = None
            with pytest.raises(HTTPException) as exc_info:
                delete_client(client_id="c-missing", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 404

    def test_delete_cross_firm_client_returns_404(self):
        from routers.clients import delete_client
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = FIRM_B_CLIENT
            with pytest.raises(HTTPException) as exc_info:
                delete_client(client_id="c-firmb", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 404

    def test_delete_error_returns_500(self):
        from routers.clients import delete_client
        with patch("routers.clients.client_repo") as mock_repo, self._no_blockers():
            mock_repo.find_by_id.return_value = ACTIVE_CLIENT
            mock_repo.soft_delete.return_value = False  # repo signals failure
            with pytest.raises(HTTPException) as exc_info:
                delete_client(client_id="c-active", current_user=USER_PARTNER_A)
        assert exc_info.value.status_code == 500


# ── is_test filtering ─────────────────────────────────────────────────────────

class TestIsTestFiltering:

    ALL_CLIENTS = [ACTIVE_CLIENT, TEST_CLIENT, ARCHIVED_CLIENT]

    def test_default_listing_excludes_archived(self):
        from routers.clients import list_clients
        # Normal clients and test clients visible, archived hidden
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_all.return_value = [ACTIVE_CLIENT, TEST_CLIENT]
            result = list_clients(
                include_archived=False, include_test=True,
                current_user=USER_PARTNER_A,
            )
        mock_repo.find_all.assert_called_once_with(
            firm_id=FIRM_A, include_archived=False, include_test=True
        )
        ids = [c["id"] for c in result["data"]["clients"]]
        assert "c-active" in ids
        assert "c-test" in ids
        assert "c-archived" not in ids

    def test_exclude_test_clients(self):
        from routers.clients import list_clients
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_all.return_value = [ACTIVE_CLIENT]
            list_clients(
                include_archived=False, include_test=False,
                current_user=USER_PARTNER_A,
            )
        mock_repo.find_all.assert_called_once_with(
            firm_id=FIRM_A, include_archived=False, include_test=False
        )

    def test_include_archived(self):
        from routers.clients import list_clients
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_all.return_value = self.ALL_CLIENTS
            list_clients(
                include_archived=True, include_test=True,
                current_user=USER_PARTNER_A,
            )
        mock_repo.find_all.assert_called_once_with(
            firm_id=FIRM_A, include_archived=True, include_test=True
        )


# ── Repository mock-mode soft delete ─────────────────────────────────────────

class TestRepositorySoftDeleteMockMode:
    """Verify mock-mode soft_delete actually sets deleted_at and hides the row."""

    def test_soft_delete_sets_deleted_at(self):
        from repositories.client_repository import ClientRepository
        repo = ClientRepository()
        client = {
            "id": "c-temp", "firm_id": FIRM_A, "client_name": "Temp",
            "status": "active", "is_test": False, "deleted_at": None,
        }
        index = {"c-temp": client}
        clients_list = [client]

        with patch("repositories.client_repository._USE_MOCK", True), \
             patch("repositories.client_repository.CLIENT_INDEX", index), \
             patch("repositories.client_repository.MOCK_CLIENTS", clients_list):
            result = repo.soft_delete("c-temp")

        assert result is True
        assert client["deleted_at"] is not None

    def test_find_by_id_hides_soft_deleted(self):
        from repositories.client_repository import ClientRepository
        repo = ClientRepository()
        client = {
            "id": "c-gone", "firm_id": FIRM_A, "client_name": "Gone",
            "status": "active", "is_test": False, "deleted_at": "2026-01-01",
        }
        index = {"c-gone": client}

        with patch("repositories.client_repository._USE_MOCK", True), \
             patch("repositories.client_repository.CLIENT_INDEX", index):
            result = repo.find_by_id("c-gone")

        assert result is None

    def test_find_all_excludes_soft_deleted(self):
        from repositories.client_repository import ClientRepository
        repo = ClientRepository()
        clients_list = [ACTIVE_CLIENT, DELETED_CLIENT]

        with patch("repositories.client_repository._USE_MOCK", True), \
             patch("repositories.client_repository.MOCK_CLIENTS", clients_list):
            results = repo.find_all()

        ids = [c["id"] for c in results]
        assert "c-active" in ids
        assert "c-deleted" not in ids

    def test_find_all_excludes_archived_by_default(self):
        from repositories.client_repository import ClientRepository
        repo = ClientRepository()
        clients_list = [ACTIVE_CLIENT, ARCHIVED_CLIENT]

        with patch("repositories.client_repository._USE_MOCK", True), \
             patch("repositories.client_repository.MOCK_CLIENTS", clients_list):
            results = repo.find_all(include_archived=False)

        ids = [c["id"] for c in results]
        assert "c-active" in ids
        assert "c-archived" not in ids

    def test_find_all_includes_archived_when_requested(self):
        from repositories.client_repository import ClientRepository
        repo = ClientRepository()
        clients_list = [ACTIVE_CLIENT, ARCHIVED_CLIENT]

        with patch("repositories.client_repository._USE_MOCK", True), \
             patch("repositories.client_repository.MOCK_CLIENTS", clients_list):
            results = repo.find_all(include_archived=True)

        ids = [c["id"] for c in results]
        assert "c-active" in ids
        assert "c-archived" in ids

    def test_find_all_excludes_test_when_requested(self):
        from repositories.client_repository import ClientRepository
        repo = ClientRepository()
        clients_list = [ACTIVE_CLIENT, TEST_CLIENT]

        with patch("repositories.client_repository._USE_MOCK", True), \
             patch("repositories.client_repository.MOCK_CLIENTS", clients_list):
            results = repo.find_all(include_test=False)

        ids = [c["id"] for c in results]
        assert "c-active" in ids
        assert "c-test" not in ids


# ── Deletion blocker logic ────────────────────────────────────────────────────

class TestDeleteBlockerLogic:

    def test_no_blockers_for_clean_client(self):
        from routers.clients import _check_delete_blockers
        with patch("routers.clients.MOCK_COMPLIANCE_TASKS", []), \
             patch("routers.clients.compliance_records_repo") as mock_repo:
            mock_repo.find_all.return_value = []
            blockers = _check_delete_blockers("c-clean", FIRM_A)
        assert blockers == []

    def test_open_compliance_task_blocks_delete(self):
        from routers.clients import _check_delete_blockers
        open_task = {"client_id": "c-001", "firm_id": FIRM_A, "status": "pending", "compliance_type": "GSTR1"}
        with patch("routers.clients.MOCK_COMPLIANCE_TASKS", [open_task]), \
             patch("routers.clients.compliance_records_repo") as mock_repo:
            mock_repo.find_all.return_value = []
            blockers = _check_delete_blockers("c-001", FIRM_A)
        assert len(blockers) == 1
        assert "GSTR1" in blockers[0]

    def test_filed_compliance_task_does_not_block(self):
        from routers.clients import _check_delete_blockers
        filed_task = {"client_id": "c-001", "firm_id": FIRM_A, "status": "filed", "compliance_type": "GSTR1"}
        with patch("routers.clients.MOCK_COMPLIANCE_TASKS", [filed_task]), \
             patch("routers.clients.compliance_records_repo") as mock_repo:
            mock_repo.find_all.return_value = []
            blockers = _check_delete_blockers("c-001", FIRM_A)
        assert blockers == []

    def test_active_compliance_record_blocks_delete(self):
        from routers.clients import _check_delete_blockers
        active_record = {"id": "cr-1", "firm_id": FIRM_A, "client_id": "c-001", "status": "In Progress"}
        with patch("routers.clients.MOCK_COMPLIANCE_TASKS", []), \
             patch("routers.clients.compliance_records_repo") as mock_repo:
            mock_repo.find_all.return_value = [active_record]
            blockers = _check_delete_blockers("c-001", FIRM_A)
        assert len(blockers) == 1
        assert "compliance record" in blockers[0]

    def test_filed_compliance_record_does_not_block(self):
        from routers.clients import _check_delete_blockers
        filed_record = {"id": "cr-1", "firm_id": FIRM_A, "client_id": "c-001", "status": "Filed"}
        with patch("routers.clients.MOCK_COMPLIANCE_TASKS", []), \
             patch("routers.clients.compliance_records_repo") as mock_repo:
            mock_repo.find_all.return_value = [filed_record]
            blockers = _check_delete_blockers("c-001", FIRM_A)
        assert blockers == []

    def test_cross_firm_tasks_not_counted_as_blockers(self):
        from routers.clients import _check_delete_blockers
        other_firm_task = {"client_id": "c-001", "firm_id": FIRM_B, "status": "pending", "compliance_type": "GSTR1"}
        with patch("routers.clients.MOCK_COMPLIANCE_TASKS", [other_firm_task]), \
             patch("routers.clients.compliance_records_repo") as mock_repo:
            mock_repo.find_all.return_value = []
            blockers = _check_delete_blockers("c-001", FIRM_A)
        assert blockers == []


# ── PATCH → archived blocked ──────────────────────────────────────────────────

class TestPatchArchivedBlocked:

    def test_patch_to_archived_status_returns_400(self):
        from routers.clients import update_client
        from models.client import ClientUpdate, ClientStatus
        with patch("routers.clients.client_repo") as mock_repo:
            mock_repo.find_by_id.return_value = ACTIVE_CLIENT
            body = ClientUpdate(status=ClientStatus.ARCHIVED)
            with pytest.raises(HTTPException) as exc_info:
                update_client(client_id="c-active", body=body, current_user=USER_MANAGER_A)
        assert exc_info.value.status_code == 400
        assert "archive" in exc_info.value.detail.lower()
