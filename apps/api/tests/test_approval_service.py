"""Module 9.0 / M4 — approval engine: lifecycle, execution, audit, bypass guards."""
import pytest
from fastapi import HTTPException

import services.approval_service as svc
import repositories.approval_repository as arepo
import repositories.assignment_repository as asg

PARTNER = {"id": "p", "firm_id": "F1", "role": "Partner", "email": "p@f"}
EXEC = {"id": "e", "firm_id": "F1", "role": "Executive", "email": "e@f"}
OTHER = {"id": "x", "firm_id": "F1", "role": "Executive", "email": "x@f"}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    arepo._MOCK_REQUESTS.clear()
    asg._MOCK_ASSIGNMENTS.clear()
    audit = []
    monkeypatch.setattr(svc, "log_event", lambda *a, **k: audit.append({"a": a, "k": k}))
    yield audit
    arepo._MOCK_REQUESTS.clear()
    asg._MOCK_ASSIGNMENTS.clear()


def _actions(audit):
    return [e["a"][3] for e in audit]  # (firm, entity_type, entity_id, action)


def test_create_request_is_pending_and_audited(_reset):
    req = svc.create_request("F1", "assignment_create", {"user_id": "e", "client_id": "C1"}, EXEC)
    assert req["status"] == "pending"
    assert req["summary"]
    assert "request_created" in _actions(_reset)


def test_unknown_type_rejected():
    with pytest.raises(HTTPException) as ei:
        svc.create_request("F1", "nope", {}, EXEC)
    assert ei.value.status_code == 400


def test_missing_payload_field_rejected():
    with pytest.raises(HTTPException) as ei:
        svc.create_request("F1", "assignment_create", {"user_id": "e"}, EXEC)
    assert ei.value.status_code == 422


def test_approve_executes_real_mutation(_reset):
    req = svc.create_request("F1", "assignment_create", {"user_id": "e", "client_id": "C1"}, EXEC)
    # Not yet executed.
    assert asg.assignment_repo.list_for_user("F1", "e") == []
    out = svc.approve("F1", req["id"], PARTNER)
    assert out["status"] == "approved"
    # The handler actually created the assignment.
    assert asg.assignment_repo.list_for_user("F1", "e") == ["C1"]
    assert "approved" in _actions(_reset)


def test_reject_does_not_execute(_reset):
    req = svc.create_request("F1", "assignment_create", {"user_id": "e", "client_id": "C1"}, EXEC)
    out = svc.reject("F1", req["id"], PARTNER, reason="not needed")
    assert out["status"] == "rejected"
    assert asg.assignment_repo.list_for_user("F1", "e") == []   # never executed
    assert "rejected" in _actions(_reset)


def test_cannot_decide_twice(_reset):
    req = svc.create_request("F1", "assignment_create", {"user_id": "e", "client_id": "C1"}, EXEC)
    svc.approve("F1", req["id"], PARTNER)
    with pytest.raises(HTTPException) as ei:   # bypass attempt: re-approve
        svc.approve("F1", req["id"], PARTNER)
    assert ei.value.status_code == 409


def test_approve_missing_request_404():
    with pytest.raises(HTTPException) as ei:
        svc.approve("F1", "apr-missing", PARTNER)
    assert ei.value.status_code == 404


def test_cancel_only_requester_or_partner(_reset):
    req = svc.create_request("F1", "assignment_create", {"user_id": "e", "client_id": "C1"}, EXEC)
    with pytest.raises(HTTPException) as ei:   # another exec cannot cancel
        svc.cancel("F1", req["id"], OTHER)
    assert ei.value.status_code == 403
    out = svc.cancel("F1", req["id"], EXEC)    # requester can
    assert out["status"] == "cancelled"


def test_partner_can_cancel_any(_reset):
    req = svc.create_request("F1", "assignment_create", {"user_id": "e", "client_id": "C1"}, EXEC)
    assert svc.cancel("F1", req["id"], PARTNER)["status"] == "cancelled"


def test_invalid_role_change_blocked_at_execution(_reset):
    req = svc.create_request("F1", "role_change", {"user_id": "u1", "role": "Wizard"}, EXEC)
    with pytest.raises(HTTPException) as ei:
        svc.approve("F1", req["id"], PARTNER)
    assert ei.value.status_code == 400


def test_firm_isolation(_reset):
    req = svc.create_request("F1", "assignment_create", {"user_id": "e", "client_id": "C1"}, EXEC)
    # A different firm cannot see or act on the request.
    assert svc.get_request("F2", req["id"]) is None
    with pytest.raises(HTTPException) as ei:
        svc.approve("F2", req["id"], {"id": "p2", "firm_id": "F2", "role": "Partner"})
    assert ei.value.status_code == 404
