"""M6 — identity administration backend: role matrix, audit, session revocation."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.identity as idmod
import repositories.login_events_repository as le
from routers.identity import router as identity_router
from core.auth import get_current_user

PARTNER = {"id": "p", "firm_id": "F1", "role": "Partner", "email": "p@f"}
MANAGER = {"id": "m", "firm_id": "F1", "role": "Manager", "email": "m@f"}
EXEC = {"id": "e", "firm_id": "F1", "role": "Executive", "email": "e@f"}


class _FakeUserRepo:
    def __init__(self):
        self.users = {"t1": {"id": "t1", "firm_id": "F1", "role": "Executive", "email": "t@f", "is_active": True}}
    def find_by_id(self, uid):
        return self.users.get(uid)
    def update(self, uid, data):
        self.users.setdefault(uid, {"id": uid}).update(data)
        return self.users[uid]
    def create(self, data):
        uid = "new1"; self.users[uid] = {"id": uid, **data}; return self.users[uid]
    def find_all(self, firm_id=None):
        return [u for u in self.users.values() if u.get("firm_id") == firm_id]


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    le._MOCK_EVENTS.clear()
    fake = _FakeUserRepo()
    monkeypatch.setattr(idmod, "user_repo", fake)
    audit = []
    monkeypatch.setattr(idmod, "log_event", lambda *a, **k: audit.append(a[3]))
    yield fake, audit
    le._MOCK_EVENTS.clear()


def _client(user):
    app = FastAPI()
    app.include_router(identity_router)
    app.dependency_overrides[get_current_user] = lambda: user
    return TestClient(app, raise_server_exceptions=False)


# ── RBAC matrix ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("user,code", [(PARTNER, 200), (MANAGER, 403), (EXEC, 403)])
def test_only_partner_can_suspend(user, code):
    assert _client(user).post("/api/identity/users/t1/suspend").status_code == code


def test_manager_can_read_login_history():
    assert _client(MANAGER).get("/api/identity/login-history").status_code == 200
    assert _client(EXEC).get("/api/identity/login-history").status_code == 403


# ── Suspend kills sessions + audits ─────────────────────────────────────────────

def test_suspend_sets_inactive_and_revokes_sessions(_setup):
    fake, audit = _setup
    _client(PARTNER).post("/api/identity/users/t1/suspend")
    assert fake.users["t1"]["is_active"] is False
    assert fake.users["t1"].get("sessions_revoked_at")  # session revocation stamped
    assert "suspend" in audit
    assert any(e["event"] == "suspended" for e in le._MOCK_EVENTS)


def test_force_logout_stamps_revocation_and_audits(_setup):
    fake, audit = _setup
    _client(PARTNER).post("/api/identity/users/t1/force-logout")
    assert fake.users["t1"].get("sessions_revoked_at")
    assert "force_logout" in audit
    assert any(e["event"] == "forced_logout" for e in le._MOCK_EVENTS)


def test_force_logout_all(_setup):
    fake, _ = _setup
    r = _client(PARTNER).post("/api/identity/force-logout-all")
    assert r.status_code == 200 and r.json()["data"]["users_affected"] >= 1


def test_role_change_validates_canonical(_setup):
    assert _client(PARTNER).patch("/api/identity/users/t1/role", json={"role": "Wizard"}).status_code == 400
    assert _client(PARTNER).patch("/api/identity/users/t1/role", json={"role": "Manager"}).status_code == 200


def test_create_user_rejects_bad_role():
    assert _client(PARTNER).post("/api/identity/users",
                                 json={"full_name": "X", "email": "x@f", "role": "Nope"}).status_code == 400


def test_cross_firm_user_not_found():
    # t1 is in F1; a Partner from F2 cannot act on it.
    p2 = {"id": "p2", "firm_id": "F2", "role": "Partner", "email": "p2@f"}
    assert _client(p2).post("/api/identity/users/t1/suspend").status_code == 404
