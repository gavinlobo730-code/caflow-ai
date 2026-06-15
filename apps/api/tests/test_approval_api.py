"""Module 9.0 / M4 — approval API role matrix + audit + bypass attempts."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import services.approval_service as svc
import repositories.approval_repository as arepo
import repositories.assignment_repository as asg
from routers.approvals import router as approvals_router
from core.auth import get_current_user

PARTNER = {"id": "p", "firm_id": "F1", "role": "Partner", "email": "p@f"}
MANAGER = {"id": "m", "firm_id": "F1", "role": "Manager", "email": "m@f"}
EXEC = {"id": "e", "firm_id": "F1", "role": "Executive", "email": "e@f"}
REVIEWER = {"id": "r", "firm_id": "F1", "role": "Reviewer", "email": "r@f"}
CLIENT = {"id": "c", "firm_id": "F1", "role": "Client", "email": "c@f"}

REQ = {"request_type": "assignment_create", "payload": {"user_id": "e", "client_id": "C1"}}


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    arepo._MOCK_REQUESTS.clear()
    asg._MOCK_ASSIGNMENTS.clear()
    audit = []
    monkeypatch.setattr(svc, "log_event", lambda *a, **k: audit.append(a[3]))
    yield audit
    arepo._MOCK_REQUESTS.clear()
    asg._MOCK_ASSIGNMENTS.clear()


def _client(user):
    app = FastAPI()
    app.include_router(approvals_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


# ── Who may request (maker = Executive+) ──────────────────────────────────────

def test_executive_can_request():
    assert _client(EXEC).post("/api/approvals", json=REQ).status_code == 200


def test_reviewer_and_client_cannot_request():
    assert _client(REVIEWER).post("/api/approvals", json=REQ).status_code == 403
    assert _client(CLIENT).post("/api/approvals", json=REQ).status_code == 403


# ── Who may approve (checker = Partner only) ──────────────────────────────────

def _make_request(user=EXEC):
    return _client(user).post("/api/approvals", json=REQ).json()["data"]["id"]


def test_partner_can_approve():
    rid = _make_request()
    r = _client(PARTNER).post(f"/api/approvals/{rid}/approve")
    assert r.status_code == 200
    assert asg.assignment_repo.list_for_user("F1", "e") == ["C1"]  # executed


def test_manager_cannot_approve():
    rid = _make_request()
    assert _client(MANAGER).post(f"/api/approvals/{rid}/approve").status_code == 403


def test_executive_cannot_approve_own_request():
    # Bypass attempt: maker trying to self-approve.
    rid = _make_request()
    assert _client(EXEC).post(f"/api/approvals/{rid}/approve").status_code == 403
    assert asg.assignment_repo.list_for_user("F1", "e") == []  # not executed


# ── Read (Manager+) ────────────────────────────────────────────────────────────

def test_manager_can_read_inbox():
    _make_request()
    r = _client(MANAGER).get("/api/approvals?status=pending")
    assert r.status_code == 200
    assert len(r.json()["data"]["requests"]) == 1


# ── Reject / cancel / bypass ──────────────────────────────────────────────────

def test_reject_flow():
    rid = _make_request()
    r = _client(PARTNER).post(f"/api/approvals/{rid}/reject", json={"reason": "no"})
    assert r.status_code == 200 and r.json()["data"]["status"] == "rejected"


def test_double_approve_conflict():
    rid = _make_request()
    _client(PARTNER).post(f"/api/approvals/{rid}/approve")
    assert _client(PARTNER).post(f"/api/approvals/{rid}/approve").status_code == 409


# ── Audit integration ─────────────────────────────────────────────────────────

def test_all_transitions_audited(_reset):
    audit = _reset
    rid = _make_request()
    _client(PARTNER).post(f"/api/approvals/{rid}/reject", json={"reason": "x"})
    rid2 = _make_request()
    _client(PARTNER).post(f"/api/approvals/{rid2}/approve")
    rid3 = _make_request()
    _client(EXEC).post(f"/api/approvals/{rid3}/cancel")
    assert {"request_created", "rejected", "approved", "cancelled"}.issubset(set(audit))
