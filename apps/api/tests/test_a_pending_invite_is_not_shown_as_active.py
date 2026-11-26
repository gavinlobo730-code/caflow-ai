"""A staff invitation that has not been accepted is not shown as Active (PRE-A-020).

WHAT WAS WRONG
    `POST /api/identity/users` creates the invited member's row at once, with `is_active` true and `status`
    'invited', a single-use token and an expiry. The Team screen read `is_active` alone, so a member who had
    never signed in showed as Active beside the colleagues who work there (found by the owner on 15-11-2026,
    inviting a test member on the live site).

WHAT THIS HOLDS
    `domain/firm/member_state.member_state` is the one rule (active, invited, invite_expired, inactive) and
    `GET /api/identity/users` serves its answer on every row, asked BEFORE the invite token is stripped (the
    token is part of the answer: an invitation without one can no longer be used). The screen only words the
    answer (`apps/web/lib/team/memberState.ts`, tested there).
"""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import routers.identity as idmod
from domain.firm.invite_token import lookup_values
from services import staff_invite_service
from core.auth import get_current_user, get_jwt_user
from domain.firm.member_state import MEMBER_STATES, member_state
from routers.identity import invite_router, router as identity_router

NOW = datetime(2026, 11, 16, 0, 0, tzinfo=timezone.utc)
LATER = (NOW + timedelta(days=7)).isoformat()
EARLIER = (NOW - timedelta(minutes=1)).isoformat()


def _invited(**extra):
    return {"is_active": True, "status": "invited", "auth_user_id": None, "invite_token": "t",
            "invite_expires_at": LATER, **extra}


def test_an_outstanding_invitation_is_invited_and_never_active():
    assert member_state(_invited(), NOW) == "invited"


def test_an_invitation_past_its_expiry_or_without_its_token_is_expired():
    assert member_state(_invited(invite_expires_at=EARLIER), NOW) == "invite_expired"
    assert member_state(_invited(invite_token=None), NOW) == "invite_expired"
    assert member_state(_invited(invite_expires_at=None), NOW) == "invite_expired"
    assert member_state(_invited(invite_expires_at="not a date"), NOW) == "invite_expired"


def test_the_expiry_is_an_instant_and_a_naive_stamp_reads_as_utc():
    # one second either side of the expiry, written with an offset and without one
    assert member_state(_invited(invite_expires_at="2026-11-16T05:30:01+05:30"), NOW) == "invited"
    assert member_state(_invited(invite_expires_at="2026-11-16T05:29:59+05:30"), NOW) == "invite_expired"
    assert member_state(_invited(invite_expires_at="2026-11-16T00:00:01"), NOW) == "invited"
    assert member_state(_invited(invite_expires_at="2026-11-16T00:00:00Z"), NOW) == "invite_expired"


def test_an_accepted_member_is_active_and_a_switched_off_row_is_inactive_whatever_else_it_says():
    assert member_state({"is_active": True, "status": "active", "auth_user_id": "a"}, NOW) == "active"
    assert member_state({"is_active": False, "status": "active", "auth_user_id": "a"}, NOW) == "inactive"
    assert member_state(_invited(is_active=False), NOW) == "inactive"


def test_a_row_that_was_never_an_invitation_reads_as_it_always_did():
    # rows written before invitations existed, and the mock fixtures, carry no auth id and no 'invited' status
    assert member_state({"is_active": True, "status": "active"}, NOW) == "active"
    assert member_state({"is_active": True}, NOW) == "active"


def test_every_answer_is_one_of_the_four_states():
    rows = [_invited(), _invited(invite_token=None), {"is_active": False}, {"auth_user_id": "a"}, {}]
    assert {member_state(r, NOW) for r in rows} <= set(MEMBER_STATES)


# ── the route ──────────────────────────────────────────────────────────────────

class _Repo:
    def __init__(self):
        self.users = {
            "a": {"id": "a", "firm_id": "F1", "role": "Partner", "email": "a@f", "is_active": True,
                  "status": "active", "auth_user_id": "auth-a"},
        }

    def create(self, data):
        uid = f"u{len(self.users)}"
        self.users[uid] = {"id": uid, **data}
        return self.users[uid]

    def find_all(self, firm_id=None):
        return [u for u in self.users.values() if u.get("firm_id") == firm_id]

    def find_by_invite_token(self, token):
        values = lookup_values(token)
        return next((u for u in self.users.values()
                     if u.get("invite_token") in values and not u.get("auth_user_id")), None)

    def find_linked_member(self, auth_user_id):
        return next((u for u in self.users.values() if u.get("auth_user_id") == auth_user_id), None)

    def update(self, uid, data, *, firm_id):
        u = self.users.get(uid)
        if not u or u.get("firm_id") != firm_id:
            return None
        u.update(data)
        return u


PARTNER = {"id": "a", "firm_id": "F1", "role": "Partner", "email": "a@f", "auth_user_id": "auth-a"}


#: The tokens the invitations' mails carried: the store keeps only their hashes (POST-A-445).
issued: list[str] = []


@pytest.fixture()
def repo(monkeypatch):
    issued.clear()

    def _issue():
        issued.append(f"tok-{len(issued)}-" + "y" * 32)
        return issued[-1]
    monkeypatch.setattr(staff_invite_service, "_new_token", _issue)
    fake = _Repo()
    monkeypatch.setattr(idmod, "user_repo", fake)
    monkeypatch.setattr(idmod, "log_event", lambda *a, **k: None)
    return fake


def _client(jwt_user=None):
    app = FastAPI()
    app.include_router(identity_router)
    app.include_router(invite_router)
    app.dependency_overrides[get_current_user] = lambda: PARTNER
    if jwt_user:
        app.dependency_overrides[get_jwt_user] = lambda: jwt_user
    return TestClient(app, raise_server_exceptions=False)


def _states(client):
    rows = client.get("/api/identity/users").json()["data"]["users"]
    assert all("invite_token" not in r for r in rows), "the bearer secret must still be stripped"
    return {r["email"]: r["member_state"] for r in rows}


def test_a_fresh_invite_is_listed_as_invited_and_becomes_active_only_when_accepted(repo):
    client = _client()
    made = client.post("/api/identity/users", json={"full_name": "Team Test", "email": "t@f", "role": "Manager"})
    assert made.status_code == 200
    assert _states(client) == {"a@f": "active", "t@f": "invited"}

    assert "invite_token" not in made.json()["data"], "the answer to the Partner no longer carries the token"
    token = issued[-1]
    accepted = _client({"auth_user_id": "auth-t", "email": "t@f"}).post("/api/identity/accept-invite",
                                                                         json={"token": token})
    assert accepted.status_code == 200
    assert _states(client) == {"a@f": "active", "t@f": "active"}


def test_an_invite_left_past_its_expiry_is_listed_as_expired(repo):
    client = _client()
    made = client.post("/api/identity/users", json={"full_name": "Late", "email": "late@f", "role": "Executive"})
    # the route asks the real clock, so the expiry is set well before any day this test runs on
    repo.users[made.json()["data"]["id"]]["invite_expires_at"] = "2020-01-01T00:00:00+00:00"
    assert _states(client)["late@f"] == "invite_expired"
