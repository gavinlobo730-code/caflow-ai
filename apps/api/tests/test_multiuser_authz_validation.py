"""
Multi-user authorization validation (pre JWT/MFA-cutover gate).

Builds the full persona matrix —
  Partner, Manager A/B, Executive A/B, Client A/B —
with explicit client assignments, and asserts cross-client / cross-manager
access is denied at BOTH layers:

  1. the central authorization engine (core.authz.can_access_client), and
  2. the router-level guard main.py attaches to every client-scoped router
     (services.internal_client_service.require_client_access) — for client_id in
     the query string AND in a JSON request body (the body path is the Module 9.0
     hardening: body-scoped writes previously bypassed assignment enforcement).

Enforcement is forced on (mock mode disabled) with a stubbed assignment set, so
no live DB is required.
"""
import pytest
from fastapi import FastAPI, APIRouter, Depends, Query, Body, Form
from fastapi.testclient import TestClient

import core.authz as authz
import services.internal_client_service as ics
from core.auth import get_current_user
from services.internal_client_service import assert_partner_for_internal_id

# ── Personas (firm F1; clients C_A and C_B) ──────────────────────────────────
PARTNER   = {"id": "u-partner",   "firm_id": "F1", "role": "Partner"}
MANAGER_A = {"id": "u-mgr-a",     "firm_id": "F1", "role": "Manager"}
MANAGER_B = {"id": "u-mgr-b",     "firm_id": "F1", "role": "Manager"}
EXEC_A    = {"id": "u-exec-a",    "firm_id": "F1", "role": "Executive"}
EXEC_B    = {"id": "u-exec-b",    "firm_id": "F1", "role": "Executive"}
CLIENT_A  = {"id": "u-client-a",  "firm_id": "F1", "role": "Client"}
CLIENT_B  = {"id": "u-client-b",  "firm_id": "F1", "role": "Client"}

# Each non-Partner persona is assigned to exactly one client's book.
ASSIGNMENTS = {
    "u-mgr-a": {"C_A"}, "u-mgr-b": {"C_B"},
    "u-exec-a": {"C_A"}, "u-exec-b": {"C_B"},
    "u-client-a": {"C_A"}, "u-client-b": {"C_B"},
}


@pytest.fixture(autouse=True)
def enforced(monkeypatch):
    """Force the real (non-mock) enforcement path with fixed assignments.
    C_A and C_B both belong to firm F1 (every persona's firm) -- this suite's
    scenarios are all within-firm assignment scoping; cross-FIRM denial is
    covered separately by test_authz_engine.py's F1 regression tests."""
    monkeypatch.setattr(authz, "_USE_MOCK", False)
    monkeypatch.setattr(authz, "assigned_client_ids", lambda u: ASSIGNMENTS.get(u.get("id"), set()))
    monkeypatch.setattr(authz, "_client_belongs_to_firm", lambda client_id, firm_id: firm_id == "F1")


def _client_for(user):
    """A TestClient whose every request authenticates as `user`, with the real
    require_client_access guard attached exactly as main.py attaches it."""
    app = FastAPI()
    r = APIRouter()

    @r.get("/list")
    def list_ep(client_id: str = Query(...)):
        return {"ok": True}

    @r.post("/create")
    def create_ep(payload: dict = Body(...)):
        return {"ok": True}

    app.include_router(r, dependencies=[Depends(ics.require_client_access)])
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


# ── Layer 1: authorization engine ────────────────────────────────────────────

def test_engine_partner_is_firmwide():
    assert authz.can_access_client(PARTNER, "C_A") is True
    assert authz.can_access_client(PARTNER, "C_B") is True


@pytest.mark.parametrize("user,own,other", [
    (MANAGER_A, "C_A", "C_B"),
    (MANAGER_B, "C_B", "C_A"),   # cross-manager
    (EXEC_A, "C_A", "C_B"),
    (EXEC_B, "C_B", "C_A"),
    (CLIENT_A, "C_A", "C_B"),
    (CLIENT_B, "C_B", "C_A"),
])
def test_engine_assignment_scoped(user, own, other):
    assert authz.can_access_client(user, own) is True
    assert authz.can_access_client(user, other) is False


# ── Layer 2: router guard — cross-client READ (query string) ─────────────────

def test_guard_partner_reads_any_client():
    c = _client_for(PARTNER)
    assert c.get("/list?client_id=C_A").status_code == 200
    assert c.get("/list?client_id=C_B").status_code == 200


@pytest.mark.parametrize("user,own,other", [
    (MANAGER_A, "C_A", "C_B"),
    (MANAGER_B, "C_B", "C_A"),
    (EXEC_A, "C_A", "C_B"),
    (EXEC_B, "C_B", "C_A"),
])
def test_guard_read_blocks_cross_client(user, own, other):
    c = _client_for(user)
    assert c.get(f"/list?client_id={own}").status_code == 200
    # 404 (not 403) so the client's existence is not disclosed.
    assert c.get(f"/list?client_id={other}").status_code == 404


# ── Layer 2: router guard — cross-client WRITE (JSON body) ───────────────────
# This is the Module 9.0 hardening: a body-scoped write to an unassigned client
# must be blocked, not just query/path access.

def test_guard_partner_writes_any_client():
    c = _client_for(PARTNER)
    assert c.post("/create", json={"client_id": "C_B", "amount": 1}).status_code == 200


@pytest.mark.parametrize("user,own,other", [
    (MANAGER_A, "C_A", "C_B"),
    (MANAGER_B, "C_B", "C_A"),
    (EXEC_A, "C_A", "C_B"),
    (EXEC_B, "C_B", "C_A"),
])
def test_guard_write_blocks_cross_client(user, own, other):
    c = _client_for(user)
    # A write to the assigned client still works (body parses normally).
    assert c.post("/create", json={"client_id": own, "amount": 1}).status_code == 200
    # A write to an UNASSIGNED client in the body is denied.
    assert c.post("/create", json={"client_id": other, "amount": 1}).status_code == 404


def test_guard_noop_without_client_id():
    # Firm-level requests (no client_id anywhere) are unaffected for everyone.
    assert _client_for(EXEC_A).post("/create", json={"amount": 1}).status_code == 200


# ── Layer 2b: multipart/form writes (document upload class) ──────────────────
# Form-data client_id bypasses the central JSON guard, so those handlers scope
# explicitly via assert_partner_for_internal_id + assert_client_access. This
# replicates that handler pattern to lock the behaviour.

def _form_client_for(user):
    app = FastAPI()
    r = APIRouter()

    @r.post("/upload")
    def upload_ep(client_id: str = Form(...), current_user: dict = Depends(get_current_user)):
        assert_partner_for_internal_id(client_id, current_user)
        authz.assert_client_access(current_user, client_id)
        return {"ok": True}

    app.include_router(r)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("user,own,other", [
    (EXEC_A, "C_A", "C_B"),
    (MANAGER_B, "C_B", "C_A"),
])
def test_multipart_upload_blocks_cross_client(user, own, other):
    c = _form_client_for(user)
    assert c.post("/upload", data={"client_id": own}).status_code == 200
    assert c.post("/upload", data={"client_id": other}).status_code == 404


def test_multipart_upload_partner_any_client():
    c = _form_client_for(PARTNER)
    assert c.post("/upload", data={"client_id": "C_B"}).status_code == 200
