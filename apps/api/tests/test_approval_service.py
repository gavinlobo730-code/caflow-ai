"""Module 9.0 / M4 — approval engine: lifecycle, execution, audit, bypass guards.

The engine is exercised with a test-only request type (`test_grant`) registered for the length of each test, so what is held
here is the ENGINE (a request is pending until a Partner decides it, a decision runs the action once, firms are isolated)
and not any business action. The first real type is `mfa_reset`, held in
tests/test_a_lost_authenticator_is_reset_by_a_partner_other_than_the_asker.py; the staff and assignment types were retired
on 19-10-2026 (POST-A-240) and are held as retired at the foot of this file.
"""
import pytest
from fastapi import HTTPException

import services.approval_service as svc
import repositories.approval_repository as arepo

PARTNER = {"id": "p", "firm_id": "F1", "role": "Partner", "email": "p@f"}
EXEC = {"id": "e", "firm_id": "F1", "role": "Executive", "email": "e@f"}
OTHER = {"id": "x", "firm_id": "F1", "role": "Executive", "email": "x@f"}

# What the test action did, in order: (firm, payload). A request that was only raised, rejected or cancelled leaves it empty.
DONE: list = []
REQ_TYPE = "test_grant"
PAYLOAD = {"user_id": "e", "client_id": "C1"}


def _invalid(_firm, _payload):
    raise HTTPException(400, "Invalid role")


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    arepo._MOCK_REQUESTS.clear()
    DONE.clear()
    audit = []
    monkeypatch.setattr(svc, "log_event", lambda *a, **k: audit.append({"a": a, "k": k}))
    monkeypatch.setitem(svc._SPECS, REQ_TYPE, {
        "required": ["user_id", "client_id"],
        "summary": lambda p: f"Grant {p.get('client_id')} to {p.get('user_id')}",
        "handler": lambda firm, p: (DONE.append((firm, p)), {"granted": True})[1],
    })
    monkeypatch.setitem(svc._SPECS, "test_grant_refused", {
        "required": [], "summary": lambda p: "A grant the action refuses", "handler": _invalid,
    })
    yield audit
    arepo._MOCK_REQUESTS.clear()
    DONE.clear()


def _actions(audit):
    return [e["a"][3] for e in audit]  # (firm, entity_type, entity_id, action)


def test_create_request_is_pending_and_audited(_reset):
    req = svc.create_request("F1", REQ_TYPE, PAYLOAD, EXEC)
    assert req["status"] == "pending"
    assert req["summary"]
    assert "request_created" in _actions(_reset)


def test_unknown_type_rejected():
    with pytest.raises(HTTPException) as ei:
        svc.create_request("F1", "nope", {}, EXEC)
    assert ei.value.status_code == 400


def test_missing_payload_field_rejected():
    with pytest.raises(HTTPException) as ei:
        svc.create_request("F1", REQ_TYPE, {"user_id": "e"}, EXEC)
    assert ei.value.status_code == 422


def test_approve_executes_real_mutation(_reset):
    req = svc.create_request("F1", REQ_TYPE, PAYLOAD, EXEC)
    # Not yet executed.
    assert DONE == []
    out = svc.approve("F1", req["id"], PARTNER)
    assert out["status"] == "approved"
    # The registered action actually ran, once, for this firm and this payload.
    assert DONE == [("F1", PAYLOAD)]
    assert out["result"] == {"granted": True}
    assert "approved" in _actions(_reset)


def test_reject_does_not_execute(_reset):
    req = svc.create_request("F1", REQ_TYPE, PAYLOAD, EXEC)
    out = svc.reject("F1", req["id"], PARTNER, reason="not needed")
    assert out["status"] == "rejected"
    assert DONE == []   # never executed
    assert "rejected" in _actions(_reset)


def test_cannot_decide_twice(_reset):
    req = svc.create_request("F1", REQ_TYPE, PAYLOAD, EXEC)
    svc.approve("F1", req["id"], PARTNER)
    with pytest.raises(HTTPException) as ei:   # bypass attempt: re-approve
        svc.approve("F1", req["id"], PARTNER)
    assert ei.value.status_code == 409
    assert len(DONE) == 1, "the second approval must not run the action again"


def test_approve_missing_request_404():
    with pytest.raises(HTTPException) as ei:
        svc.approve("F1", "apr-missing", PARTNER)
    assert ei.value.status_code == 404


def test_cancel_only_requester_or_partner(_reset):
    req = svc.create_request("F1", REQ_TYPE, PAYLOAD, EXEC)
    with pytest.raises(HTTPException) as ei:   # another exec cannot cancel
        svc.cancel("F1", req["id"], OTHER)
    assert ei.value.status_code == 403
    out = svc.cancel("F1", req["id"], EXEC)    # requester can
    assert out["status"] == "cancelled"


def test_partner_can_cancel_any(_reset):
    req = svc.create_request("F1", REQ_TYPE, PAYLOAD, EXEC)
    assert svc.cancel("F1", req["id"], PARTNER)["status"] == "cancelled"


def test_an_action_that_refuses_at_execution_reaches_the_caller_and_leaves_the_request_pending(_reset):
    req = svc.create_request("F1", "test_grant_refused", {}, EXEC)
    with pytest.raises(HTTPException) as ei:
        svc.approve("F1", req["id"], PARTNER)
    assert ei.value.status_code == 400
    assert svc.get_request("F1", req["id"])["status"] == "pending", "a refused action must not read as approved"


def test_firm_isolation(_reset):
    req = svc.create_request("F1", REQ_TYPE, PAYLOAD, EXEC)
    # A different firm cannot see or act on the request.
    assert svc.get_request("F2", req["id"]) is None
    with pytest.raises(HTTPException) as ei:
        svc.approve("F2", req["id"], {"id": "p2", "firm_id": "F2", "role": "Partner"})
    assert ei.value.status_code == 404
    assert DONE == []


# ── the staff and assignment types are retired (POST-A-240, 19-10-2026) ─────────────────────────────────────────────

RETIRED_STAFF_AND_ASSIGNMENT_TYPES = (
    "user_create", "user_activation", "role_change",
    "assignment_create", "assignment_remove", "assignment_transfer",
)


@pytest.mark.parametrize("retired", RETIRED_STAFF_AND_ASSIGNMENT_TYPES)
def test_a_retired_staff_or_assignment_type_cannot_be_raised_and_the_refusal_says_why(retired):
    assert retired not in svc._SPECS and retired in svc.RETIRED_TYPES
    with pytest.raises(HTTPException) as ei:
        svc.create_request("F1", retired, {"user_id": "e", "client_id": "C1", "role": "Partner",
                                           "full_name": "x", "email": "x@f", "is_active": True,
                                           "from_user_id": "a", "to_user_id": "b"}, EXEC)
    assert ei.value.status_code == 400
    assert "no longer accepted" in ei.value.detail and "Unknown" not in ei.value.detail
    assert arepo._MOCK_REQUESTS == [], "a refused request must not be stored"


def test_an_unknown_type_is_still_called_unknown_and_not_retired():
    with pytest.raises(HTTPException) as ei:
        svc.create_request("F1", "role_chnage", {}, EXEC)   # a typo is not a retired type
    assert "Unknown request_type" in ei.value.detail


@pytest.mark.parametrize("retired", RETIRED_STAFF_AND_ASSIGNMENT_TYPES)
def test_a_stored_request_of_a_retired_staff_or_assignment_type_cannot_be_approved_but_can_be_closed(retired):
    """A row an earlier version stored. Approving it would have run a repository write that skipped the direct route's
    checks, so it is refused in words, stays pending, and can still be rejected or cancelled."""
    def stored():
        return arepo.approval_repo.create({
            "firm_id": "F1", "request_type": retired, "summary": "stored by an earlier version",
            "payload": {"user_id": "u1", "role": "Partner", "client_id": "C1"}, "status": "pending",
            "requested_by": "e", "requested_by_email": "e@f"})

    row = stored()
    with pytest.raises(HTTPException) as ei:
        svc.approve("F1", row["id"], PARTNER)
    assert ei.value.status_code == 409 and "no longer be carried out" in ei.value.detail
    assert svc.get_request("F1", row["id"])["status"] == "pending", "a refused approval must not decide the request"
    assert svc.reject("F1", row["id"], PARTNER, "retired")["status"] == "rejected"

    other = stored()
    assert svc.cancel("F1", other["id"], EXEC)["status"] == "cancelled"
    assert DONE == []
