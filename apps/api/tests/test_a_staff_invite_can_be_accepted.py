"""A staff invite can be accepted through the app as it is actually mounted.

WHAT WAS WRONG

`POST /api/identity/accept-invite` depends on `get_jwt_user` precisely because
the invitee has no `public.users` row yet — linking one is what it does. But the
identity router is mounted in main.py with `dependencies=_MFA_GUARD`, and
`mfa_guard` depends on `get_current_user`, which refuses 403 "User not found in
firm" to anybody without a linked row. Router-level dependencies run before the
handler, so EVERY invitee was refused, whatever REQUIRE_MFA was set to.

`tests/test_identity_admin.py` mounts the router on a bare FastAPI() without
main.py's dependencies, which is why nothing saw it. These go through
`main.app`.

The fix gives accept-invite its own router, mounted without the guard, and
every other identity route keeps it — asserted from the mounted app rather
than from a list of paths.

Making the route reachable made a second defect live: Deactivate is the only
control a Partner has over a pending invite, and it left the emailed token in
place while accept-invite wrote `is_active: True` — so a deactivated invitee
could still join, reactivated, at the invited role. Accept now refuses an
inactive row and no longer reactivates one, and suspending a pending invitee
clears the token.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import core.auth as auth
import routers.identity as idmod

INVITE_TOKEN = "t" * 43
INVITEE_EMAIL = "new.hire@firm.test"
ACCEPT = "/api/identity/accept-invite"


class _Result:
    def __init__(self, data):
        self.data = data


class _NoUsersRowQuery:
    """Every lookup finds nothing: the invitee has signed in and has no row."""
    def select(self, *_a, **_k): return self
    def eq(self, *_a, **_k): return self
    def maybe_single(self): return self
    def single(self): return self
    def execute(self): return _Result(None)


class _NoUsersRowSupabase:
    def table(self, _name):
        return _NoUsersRowQuery()


class _InviteRepo:
    def __init__(self):
        self.row = {
            "id": "u-invited", "firm_id": "F1", "role": "Manager",
            "full_name": "New Hire", "email": INVITEE_EMAIL, "status": "invited",
            "is_active": True, "auth_user_id": None, "invite_token": INVITE_TOKEN,
            "invite_expires_at": (datetime.now(timezone.utc) + timedelta(days=3)).isoformat(),
        }

    def find_by_id(self, uid, *, firm_id):
        r = self.row
        return r if r["id"] == uid and r["firm_id"] == firm_id else None

    def find_by_invite_token(self, token):
        r = self.row
        return r if r.get("invite_token") == token and not r.get("auth_user_id") else None

    def update(self, uid, data, *, firm_id):
        if uid != self.row["id"] or firm_id != self.row["firm_id"]:
            return None
        self.row.update(data)
        return self.row


@pytest.fixture
def invitee(monkeypatch):
    """The real JWT path of core.auth, for a caller who has no users row."""
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")

    class _Key:
        key = "k"

    class _JWKS:
        def get_signing_key_from_jwt(self, _t):
            return _Key()

    monkeypatch.setattr(auth, "_get_jwks_client", lambda: _JWKS())
    monkeypatch.setattr(auth.jwt, "decode", lambda *a, **k: {
        "sub": "auth-invitee", "email": INVITEE_EMAIL, "aal": "aal1"})
    monkeypatch.setattr(auth, "get_service_supabase", lambda: _NoUsersRowSupabase())
    monkeypatch.setattr(auth, "_user_lookup_cache", {})
    repo = _InviteRepo()
    monkeypatch.setattr(idmod, "user_repo", repo)
    monkeypatch.setattr(idmod, "log_event", lambda *a, **k: None)
    return repo


def _app_client():
    import main
    return TestClient(main.app, raise_server_exceptions=False)


@pytest.mark.parametrize("require_mfa", ["false", "true"])
def test_an_invitee_with_no_users_row_can_accept_through_the_real_app(
        invitee, monkeypatch, require_mfa):
    monkeypatch.setenv("REQUIRE_MFA", require_mfa)
    r = _app_client().post(ACCEPT, json={"token": INVITE_TOKEN},
                           headers={"Authorization": "Bearer x"})
    assert r.status_code == 200, (r.status_code, r.text)
    body = r.json()
    assert body["success"] is True
    assert body["data"] == {"firm_id": "F1", "role": "Manager", "full_name": "New Hire"}
    assert invitee.row["auth_user_id"] == "auth-invitee"
    assert invitee.row["status"] == "active"
    assert invitee.row["invite_token"] is None


def test_the_unguarded_route_still_needs_a_verified_token(invitee):
    r = _app_client().post(ACCEPT, json={"token": INVITE_TOKEN})
    assert r.status_code == 401
    assert invitee.row["auth_user_id"] is None


def test_the_unguarded_route_still_refuses_an_unknown_invite(invitee):
    r = _app_client().post(ACCEPT, json={"token": "not-the-token"},
                           headers={"Authorization": "Bearer x"})
    assert r.status_code == 404
    assert invitee.row["auth_user_id"] is None


def test_the_unguarded_route_still_refuses_another_mailbox(invitee, monkeypatch):
    monkeypatch.setattr(auth.jwt, "decode", lambda *a, **k: {
        "sub": "auth-stranger", "email": "stranger@elsewhere.test", "aal": "aal1"})
    r = _app_client().post(ACCEPT, json={"token": INVITE_TOKEN},
                           headers={"Authorization": "Bearer x"})
    assert r.status_code == 404
    assert invitee.row["auth_user_id"] is None


def test_a_deactivated_invitee_cannot_accept_the_link_they_were_sent(invitee):
    # Deactivate is the only control a Partner has over a pending invite, so
    # the emailed link must stop working even if the token survived.
    invitee.row["is_active"] = False
    r = _app_client().post(ACCEPT, json={"token": INVITE_TOKEN},
                           headers={"Authorization": "Bearer x"})
    assert r.status_code == 404
    assert invitee.row["auth_user_id"] is None
    assert invitee.row["is_active"] is False


def test_deactivating_a_pending_invitee_withdraws_the_link(invitee):
    from fastapi import FastAPI
    from core.auth import get_current_user

    app = FastAPI()
    app.include_router(idmod.router)
    app.dependency_overrides[get_current_user] = lambda: {
        "id": "p", "firm_id": "F1", "role": "Partner", "email": "p@firm.test"}
    r = TestClient(app, raise_server_exceptions=False).post(
        f"/api/identity/users/{invitee.row['id']}/suspend")
    assert r.status_code == 200, r.text
    assert invitee.row["invite_token"] is None
    assert invitee.row["invite_expires_at"] is None


def _identity_routes_and_whether_guarded():
    """One (METHOD path, guarded) pair per MOUNTED route. A list, not a dict:
    a route mounted twice must show up twice, whichever copy came last."""
    import main
    from core.auth import mfa_guard

    out = []
    for route in main.app.routes:
        path = str(getattr(route, "path", ""))
        if not path.startswith("/api/identity"):
            continue
        deps = getattr(getattr(route, "dependant", None), "dependencies", [])
        guarded = mfa_guard in {getattr(d, "call", None) for d in deps}
        for method in sorted(getattr(route, "methods", set()) - {"HEAD", "OPTIONS"}):
            out.append((f"{method} {path}", guarded))
    return out


def test_accept_invite_is_the_only_identity_route_without_the_mfa_guard():
    rows = _identity_routes_and_whether_guarded()
    assert len(rows) >= 10, f"the sweep found only {sorted(rows)} — bad prefix?"
    unguarded = sorted(k for k, g in rows if not g)
    assert unguarded == [f"POST {ACCEPT}"], unguarded


def test_accept_invite_is_mounted_exactly_once():
    rows = _identity_routes_and_whether_guarded()
    assert [k for k, _ in rows if k.endswith(" " + ACCEPT)] == [f"POST {ACCEPT}"], rows
