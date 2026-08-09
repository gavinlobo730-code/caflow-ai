"""
Client-assignment scope on the CA-facing portal management routers
(portal.py, portal_access.py).

Both files are staff-facing (rbac("portal", ...)), distinct from
portal_self.py/portal_data.py which serve the CLIENT's own portal login
(get_current_portal_client/get_jwt_user) — a different authorization model
entirely, structurally scoped to the authenticated portal contact's own
client_id rather than a firm-staff assignment, and out of scope for this
M2 sweep.

portal.py: list_document_requests/create_document_request/list_messages/
send_message/get_dues took client_id from the query/body and never checked
it. complete_document_request is row-addressed by request_id and checked
only firm_id.

portal_access.py: list_portal_contacts/invite_portal_contact used a bespoke
_assert_client_in_firm helper (now removed) that checked firm only.
resend_portal_invite/deactivate_portal_contact are row-addressed by
contact_id and had no client check at all — only firm_id, applied inside
the service layer.
"""
import pytest
from fastapi import HTTPException

import routers.portal as portal_router
import routers.portal_access as portal_access_router
import domain.portal_service as portal_svc
import services.portal_access_service as portal_access_svc

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
EXEC_USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Executive"}
MANAGER_USER = {"id": "u2", "firm_id": FIRM, "auth_user_id": "u2", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow the rest."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(portal_router, "assert_client_access", _assert)
    monkeypatch.setattr(portal_router, "can_access_client", _can)
    monkeypatch.setattr(portal_access_router, "assert_client_access", _assert)
    monkeypatch.setattr(portal_access_router, "can_access_client", _can)
    return seen


@pytest.fixture(autouse=True)
def _clear_mock_stores():
    portal_svc.reset_mock_stores()
    portal_access_svc.reset_mock_stores()


# ══════════════════════════════════════════════════════════════════════════
# portal.py — list_document_requests / create_document_request
# ══════════════════════════════════════════════════════════════════════════

def test_listing_document_requests_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        portal_router.list_document_requests(client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_document_requests_for_an_own_client_is_allowed(deny):
    resp = portal_router.list_document_requests(client_id=MINE, current_user=EXEC_USER)
    assert resp["success"] is True


def test_creating_a_document_request_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        portal_router.create_document_request(
            portal_router.CreateDocRequestBody(client_id=THEIRS, title="Upload PAN"),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    assert portal_svc.list_document_requests(FIRM, THEIRS) == []


def test_creating_a_document_request_for_an_own_client_is_allowed(deny):
    resp = portal_router.create_document_request(
        portal_router.CreateDocRequestBody(client_id=MINE, title="Upload PAN"),
        current_user=MANAGER_USER,
    )
    assert resp["data"]["client_id"] == MINE


# ══════════════════════════════════════════════════════════════════════════
# portal.py — complete_document_request (row-addressed by request_id)
# ══════════════════════════════════════════════════════════════════════════

def test_completing_a_hidden_clients_document_request_is_refused(deny):
    req = portal_svc.create_document_request(FIRM, THEIRS, "Upload PAN")
    resp = portal_router.complete_document_request(req["id"], current_user=MANAGER_USER)
    assert resp["success"] is False
    assert resp["error"] == "Document request not found"
    assert portal_svc.list_document_requests(FIRM, THEIRS)[0]["status"] == "pending"


def test_completing_an_own_clients_document_request_is_allowed(deny):
    req = portal_svc.create_document_request(FIRM, MINE, "Upload PAN")
    resp = portal_router.complete_document_request(req["id"], current_user=MANAGER_USER)
    assert resp["success"] is True
    assert resp["data"]["status"] == "fulfilled"


def test_completing_a_missing_document_request_matches_the_hidden_message(deny):
    resp_missing = portal_router.complete_document_request("does-not-exist", current_user=MANAGER_USER)
    req = portal_svc.create_document_request(FIRM, THEIRS, "Upload PAN")
    resp_hidden = portal_router.complete_document_request(req["id"], current_user=MANAGER_USER)
    assert resp_missing["success"] is False and resp_hidden["success"] is False
    assert resp_missing["error"] == resp_hidden["error"] == "Document request not found"


# ══════════════════════════════════════════════════════════════════════════
# portal.py — messages, dues
# ══════════════════════════════════════════════════════════════════════════

def test_listing_messages_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        portal_router.list_messages(client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_messages_for_an_own_client_is_allowed(deny):
    resp = portal_router.list_messages(client_id=MINE, current_user=EXEC_USER)
    assert resp["success"] is True


def test_sending_a_message_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        portal_router.send_message(
            portal_router.SendMessageBody(client_id=THEIRS, text="hi"),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    assert portal_svc.list_messages(FIRM, THEIRS) == []


def test_sending_a_message_for_an_own_client_is_allowed(deny):
    resp = portal_router.send_message(
        portal_router.SendMessageBody(client_id=MINE, text="hi"),
        current_user=MANAGER_USER,
    )
    assert resp["data"]["client_id"] == MINE


def test_getting_dues_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        portal_router.get_dues(client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_getting_dues_for_an_own_client_is_allowed(deny):
    resp = portal_router.get_dues(client_id=MINE, current_user=EXEC_USER)
    assert resp["success"] is True


# ══════════════════════════════════════════════════════════════════════════
# portal_access.py — list_portal_contacts / invite_portal_contact
# ══════════════════════════════════════════════════════════════════════════

def test_listing_portal_contacts_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        portal_access_router.list_portal_contacts(client_id=THEIRS, current_user=EXEC_USER)
    assert exc.value.status_code == 404


def test_listing_portal_contacts_for_an_own_client_is_allowed(deny):
    resp = portal_access_router.list_portal_contacts(client_id=MINE, current_user=EXEC_USER)
    assert resp["success"] is True


def test_inviting_a_portal_contact_for_a_hidden_client_is_refused(deny):
    with pytest.raises(HTTPException) as exc:
        portal_access_router.invite_portal_contact(
            THEIRS, portal_access_router.InviteContactBody(email="a@b.com"),
            current_user=MANAGER_USER,
        )
    assert exc.value.status_code == 404
    assert portal_access_svc.list_contacts(FIRM, THEIRS) == []


def test_inviting_a_portal_contact_for_an_own_client_is_allowed(deny):
    resp = portal_access_router.invite_portal_contact(
        MINE, portal_access_router.InviteContactBody(email="a@b.com"),
        current_user=MANAGER_USER,
    )
    assert resp["data"]["contact"]["client_id"] == MINE


# ══════════════════════════════════════════════════════════════════════════
# portal_access.py — resend/deactivate (row-addressed by contact_id)
# ══════════════════════════════════════════════════════════════════════════

def test_resending_a_hidden_clients_contact_invite_is_refused(deny):
    contact = portal_access_svc.invite_contact(FIRM, THEIRS, "a@b.com", None)
    with pytest.raises(HTTPException) as exc:
        portal_access_router.resend_portal_invite(contact["id"], current_user=MANAGER_USER)
    assert exc.value.status_code == 404


def test_resending_an_own_clients_contact_invite_is_allowed(deny):
    contact = portal_access_svc.invite_contact(FIRM, MINE, "a@b.com", None)
    resp = portal_access_router.resend_portal_invite(contact["id"], current_user=MANAGER_USER)
    assert resp["success"] is True


def test_deactivating_a_hidden_clients_contact_is_refused(deny):
    contact = portal_access_svc.invite_contact(FIRM, THEIRS, "a@b.com", None)
    with pytest.raises(HTTPException) as exc:
        portal_access_router.deactivate_portal_contact(contact["id"], current_user=MANAGER_USER)
    assert exc.value.status_code == 404
    assert portal_access_svc.get_contact(FIRM, contact["id"])["status"] != "deactivated"


def test_deactivating_an_own_clients_contact_is_allowed(deny):
    contact = portal_access_svc.invite_contact(FIRM, MINE, "a@b.com", None)
    resp = portal_access_router.deactivate_portal_contact(contact["id"], current_user=MANAGER_USER)
    assert resp["data"]["contact"]["status"] == "deactivated"


def test_deactivating_a_missing_contact_matches_the_hidden_message(deny):
    with pytest.raises(HTTPException) as exc_missing:
        portal_access_router.deactivate_portal_contact("does-not-exist", current_user=MANAGER_USER)
    contact = portal_access_svc.invite_contact(FIRM, THEIRS, "a@b.com", None)
    with pytest.raises(HTTPException) as exc_hidden:
        portal_access_router.deactivate_portal_contact(contact["id"], current_user=MANAGER_USER)
    assert exc_missing.value.status_code == exc_hidden.value.status_code == 404
    assert exc_missing.value.detail == exc_hidden.value.detail
