"""
Client-assignment scope (M2) on the root Client resource router (clients.py).

Before this fix, get_client_workspace/update_client/archive_client/
restore_client checked only firm membership (_assert_firm(client, firm_id))
— any Executive/Reviewer (read) or Manager (write) in the firm could act on
ANY client in the firm, not just the clients assigned to them. Since clients
is the root/most-central resource in the app, this meant full workspace read
(compliance tasks, documents, AI insights, activity log) or edit/archive/
restore of an unassigned client.

delete_client is exempt from a *behavioral* difference in practice — it is
gated rbac("client", "delete") == _PARTNER_ONLY, the sole firm-wide role, so
by RBAC construction the assignment check can never actually deny a real
caller. It still goes through the same _assert_firm(client, current_user)
path for consistency (a Partner is always firm-wide, so can_access_client
returns True for any client in their own firm).

list_clients was already correct (filters via effective_client_ids) and is
not retested here. create_client has no existing client_id to scope against.
"""
import pytest
from unittest.mock import patch
from fastapi import HTTPException

import routers.clients as clients_router
from models.client import ClientUpdate

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"

EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "role": "Manager"}
PARTNER_USER = {"id": "u3", "firm_id": FIRM, "auth_user_id": "u3", "role": "Partner"}

MINE_CLIENT = {"id": MINE, "firm_id": FIRM, "client_name": "Mine Corp", "status": "active", "pan": "AAAAA1111A"}
THEIRS_CLIENT = {"id": THEIRS, "firm_id": FIRM, "client_name": "Theirs Corp", "status": "active", "pan": "AAAAA2222A"}
ARCHIVED_MINE = {**MINE_CLIENT, "status": "archived"}
ARCHIVED_THEIRS = {**THEIRS_CLIENT, "status": "archived"}


@pytest.fixture
def deny(monkeypatch):
    """Simulate an assignment-scoped caller who is not assigned to THEIRS."""
    seen = []

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(clients_router, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════
# get_client_workspace
# ══════════════════════════════════════════════════════════════════════════

def test_viewing_an_unassigned_clients_workspace_is_refused(deny):
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.compliance_records_repo") as mock_cr, \
         patch("routers.clients.document_repo") as mock_doc, \
         patch("routers.clients.ai_insights_repo") as mock_ai, \
         patch("routers.clients.task_repo") as mock_task:
        mock_repo.find_by_id.return_value = THEIRS_CLIENT
        mock_cr.find_all.return_value = []
        mock_doc.find_all.return_value = []
        mock_ai.find_all.return_value = []
        mock_task.find_all.return_value = []
        with pytest.raises(HTTPException) as exc:
            clients_router.get_client_workspace(client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Client not found"


def test_viewing_an_assigned_clients_workspace_is_allowed(deny):
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.compliance_records_repo") as mock_cr, \
         patch("routers.clients.document_repo") as mock_doc, \
         patch("routers.clients.ai_insights_repo") as mock_ai, \
         patch("routers.clients.task_repo") as mock_task:
        mock_repo.find_by_id.return_value = MINE_CLIENT
        mock_cr.find_all.return_value = []
        mock_doc.find_all.return_value = []
        mock_ai.find_all.return_value = []
        mock_task.find_all.return_value = []
        resp = clients_router.get_client_workspace(client_id=MINE, current_user=EXEC_USER)
    assert resp["success"] is True
    assert resp["data"]["profile"]["id"] == MINE


# ══════════════════════════════════════════════════════════════════════════
# update_client
# ══════════════════════════════════════════════════════════════════════════

def test_updating_an_unassigned_client_is_refused(deny):
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.log_event"):
        mock_repo.find_by_id.return_value = THEIRS_CLIENT
        with pytest.raises(HTTPException) as exc:
            clients_router.update_client(
                client_id=THEIRS, body=ClientUpdate(client_name="New Name"), current_user=MANAGER_USER,
            )
    assert exc.value.status_code == 404
    assert exc.value.detail == "Client not found"
    mock_repo.update.assert_not_called()


def test_updating_an_assigned_client_is_allowed(deny):
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.log_event"):
        mock_repo.find_by_id.return_value = MINE_CLIENT
        mock_repo.update.return_value = {**MINE_CLIENT, "client_name": "New Name"}
        resp = clients_router.update_client(
            client_id=MINE, body=ClientUpdate(client_name="New Name"), current_user=MANAGER_USER,
        )
    assert resp["success"] is True
    mock_repo.update.assert_called_once()


# ══════════════════════════════════════════════════════════════════════════
# archive_client
# ══════════════════════════════════════════════════════════════════════════

def test_archiving_an_unassigned_client_is_refused(deny):
    with patch("routers.clients.client_repo") as mock_repo:
        mock_repo.find_by_id.return_value = THEIRS_CLIENT
        with pytest.raises(HTTPException) as exc:
            clients_router.archive_client(client_id=THEIRS, current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Client not found"
    mock_repo.archive.assert_not_called()


def test_archiving_an_assigned_client_is_allowed(deny):
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.log_event"):
        mock_repo.find_by_id.return_value = MINE_CLIENT
        mock_repo.archive.return_value = ARCHIVED_MINE
        resp = clients_router.archive_client(client_id=MINE, current_user=MANAGER_USER)
    assert resp["data"]["client"]["status"] == "archived"


# ══════════════════════════════════════════════════════════════════════════
# restore_client
# ══════════════════════════════════════════════════════════════════════════

def test_restoring_an_unassigned_client_is_refused(deny):
    with patch("routers.clients.client_repo") as mock_repo:
        mock_repo.find_by_id.return_value = ARCHIVED_THEIRS
        with pytest.raises(HTTPException) as exc:
            clients_router.restore_client(client_id=THEIRS, current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Client not found"
    mock_repo.restore.assert_not_called()


def test_restoring_an_assigned_client_is_allowed(deny):
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.log_event"):
        mock_repo.find_by_id.return_value = ARCHIVED_MINE
        mock_repo.restore.return_value = MINE_CLIENT
        resp = clients_router.restore_client(client_id=MINE, current_user=MANAGER_USER)
    assert resp["data"]["client"]["status"] == "active"


# ══════════════════════════════════════════════════════════════════════════
# delete_client (Partner-only by RBAC construction; still exercises the guard)
# ══════════════════════════════════════════════════════════════════════════

def test_deleting_an_unassigned_client_is_refused(deny):
    with patch("routers.clients.client_repo") as mock_repo:
        mock_repo.find_by_id.return_value = THEIRS_CLIENT
        with pytest.raises(HTTPException) as exc:
            clients_router.delete_client(client_id=THEIRS, current_user=PARTNER_USER)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Client not found"
    mock_repo.soft_delete.assert_not_called()


def test_deleting_an_assigned_client_with_no_blockers_is_allowed(deny):
    with patch("routers.clients.client_repo") as mock_repo, \
         patch("routers.clients.log_event"), \
         patch("routers.clients.compliance_records_repo") as mock_cr, \
         patch("routers.clients.task_repo") as mock_task, \
         patch("routers.clients.document_repo") as mock_doc:
        mock_repo.find_by_id.return_value = MINE_CLIENT
        mock_repo.soft_delete.return_value = True
        mock_cr.find_all.return_value = []
        mock_task.find_all.return_value = []
        mock_doc.find_all.return_value = []
        resp = clients_router.delete_client(client_id=MINE, current_user=PARTNER_USER)
    assert resp["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# Message-oracle: hidden (assignment-denied) and missing must read identically
# ══════════════════════════════════════════════════════════════════════════

def test_hidden_and_missing_client_workspace_errors_match(deny):
    with patch("routers.clients.client_repo") as mock_repo:
        mock_repo.find_by_id.return_value = None
        with pytest.raises(HTTPException) as exc_missing:
            clients_router.get_client_workspace(client_id="does-not-exist", current_user=EXEC_USER)

        mock_repo.find_by_id.return_value = THEIRS_CLIENT
        with pytest.raises(HTTPException) as exc_hidden:
            clients_router.get_client_workspace(client_id=THEIRS, current_user=EXEC_USER)

    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail == "Client not found"


# ══════════════════════════════════════════════════════════════════════════
# Cross-firm still refused even when can_access_client is not consulted
# (the firm check in _assert_firm short-circuits before the assignment check)
# ══════════════════════════════════════════════════════════════════════════

def test_cross_firm_client_is_refused_before_assignment_check_runs(monkeypatch):
    calls = []
    monkeypatch.setattr(clients_router, "can_access_client", lambda u, c: calls.append(c) or True)
    other_firm_client = {**THEIRS_CLIENT, "firm_id": "firm-2"}
    with patch("routers.clients.client_repo") as mock_repo:
        mock_repo.find_by_id.return_value = other_firm_client
        with pytest.raises(HTTPException) as exc:
            clients_router.get_client_workspace(client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404
    assert exc.value.detail == "Client not found"
    # The firm mismatch short-circuits _assert_firm before can_access_client runs.
    assert calls == []
