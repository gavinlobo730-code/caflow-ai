"""
Staff identity is read and written as the SERVICE ROLE, and every query that is
addressed by an id carries the caller's firm.

WHAT WAS WRONG
    `repositories/user_repository._get_db` returned `get_supabase()`, which under
    USE_USER_JWT is the caller's `authenticated` client. On `public.users` that
    role may SELECT only its own row (`users_own_row_select`), UPDATE only
    `full_name`, and INSERT nothing (migration 153). So PATCH /api/identity/me
    500'd on the `updated_at` the repository always adds, POST /api/identity/users
    (invite) 500'd on the INSERT, and the Team list, role change, suspend,
    reactivate, force-logout and accept-invite all read a row the policy hides.

WHY SCOPING HAD TO MOVE INTO THE QUERY FIRST
    The service role bypasses RLS, so the firm filter becomes the tenant
    boundary. `update()` addressed a row by id alone, and
    `services/approval_service._h_role_change` / `_h_user_activation` updated
    `p["user_id"]` straight off a request payload with no firm check — the switch
    alone would have let an approval in one firm change another firm's staff.

These tests drive the REAL repository against an in-memory table, with
`get_supabase` wired to REFUSE: a repository still reading through the
downgraded client fails every one of them.
"""
import pytest

import core.supabase_client as sc
import repositories.user_repository as ur
from repositories.user_repository import user_repo


F1, F2 = "firm-one", "firm-two"


class _Query:
    def __init__(self, table):
        self.table = table
        self.filters = []
        self.op = "select"
        self.payload = None
        self.single = False

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self.filters.append((col, val))
        return self

    def is_(self, col, val):
        self.filters.append((col, None if val in (None, "null") else val))
        return self

    def order(self, *_a, **_k):
        return self

    def maybe_single(self):
        self.single = True
        return self

    def update(self, data):
        self.op, self.payload = "update", data
        return self

    def insert(self, data):
        self.op, self.payload = "insert", data
        return self

    def _matches(self, row):
        return all(row.get(c) == v for c, v in self.filters)

    def execute(self):
        class R:
            pass
        r = R()
        if self.op == "insert":
            row = {"id": f"u{len(self.table.rows) + 1}", **self.payload}
            self.table.rows.append(row)
            r.data = [row]
            return r
        hit = [row for row in self.table.rows if self._matches(row)]
        if self.op == "update":
            for row in hit:
                row.update(self.payload)
        r.data = (hit[0] if hit else None) if self.single else hit
        return r


class _ServiceDb:
    def __init__(self, rows):
        self.rows = rows
        self.tables_asked = []

    def table(self, name):
        assert name == "users"
        self.tables_asked.append(name)
        return _Query(self)


@pytest.fixture
def db(monkeypatch):
    rows = [
        {"id": "me", "firm_id": F1, "full_name": "Old Name", "role": "Executive",
         "email": "me@one.test", "is_active": True, "deleted_at": None,
         "auth_user_id": "auth-me"},
        {"id": "colleague", "firm_id": F1, "full_name": "Colleague", "role": "Executive",
         "email": "c@one.test", "is_active": True, "deleted_at": None,
         "auth_user_id": "auth-c"},
        {"id": "stranger", "firm_id": F2, "full_name": "Stranger", "role": "Executive",
         "email": "s@two.test", "is_active": True, "deleted_at": None,
         "auth_user_id": "auth-s"},
    ]
    fake = _ServiceDb(rows)

    def _downgraded(*_a, **_k):
        raise AssertionError("user_repository read through the downgraded "
                             "authenticated client (get_supabase)")

    monkeypatch.setattr(ur, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: fake)
    monkeypatch.setattr(sc, "get_supabase", _downgraded)
    monkeypatch.setattr("routers.identity.log_event", lambda *a, **k: None)
    return fake


def _row(db, uid):
    return next(r for r in db.rows if r["id"] == uid)


PARTNER = {"id": "p", "firm_id": F1, "role": "Partner", "email": "p@one.test",
           "auth_user_id": "auth-p"}


def test_a_staff_member_can_rename_themselves(db):
    from routers.identity import update_my_profile, MyProfileBody

    out = update_my_profile(MyProfileBody(full_name="New Name"),
                            current_user={"id": "me", "firm_id": F1, "role": "Executive"})

    assert out["success"] is True
    assert _row(db, "me")["full_name"] == "New Name"
    assert "updated_at" in _row(db, "me")


def test_a_partner_can_invite_a_member(db):
    from routers.identity import create_user, CreateUserBody

    out = create_user(CreateUserBody(full_name="New Hire", email="n@one.test", role="Manager"),
                      current_user=PARTNER)

    created = out["data"]
    assert created["firm_id"] == F1 and created["status"] == "invited"
    assert created["invite_token"]
    assert any(r.get("email") == "n@one.test" and r["firm_id"] == F1 for r in db.rows)


def test_the_team_list_is_every_member_of_the_firm_and_no_other(db):
    from routers.identity import list_users

    _row(db, "colleague")["invite_token"] = "a-live-secret"
    users = list_users(current_user=PARTNER)["data"]["users"]

    assert {u["id"] for u in users} == {"me", "colleague"}
    assert all("invite_token" not in u for u in users)


def test_a_partner_can_suspend_a_colleague_but_not_another_firms_member(db, monkeypatch):
    from fastapi import HTTPException
    from routers.identity import suspend_user
    import routers.identity as idmod

    monkeypatch.setattr(idmod.login_events_repo, "record", lambda *a, **k: None)
    suspend_user("colleague", current_user=PARTNER)
    assert _row(db, "colleague")["is_active"] is False

    with pytest.raises(HTTPException) as exc:
        suspend_user("stranger", current_user=PARTNER)
    assert exc.value.status_code == 404
    assert _row(db, "stranger")["is_active"] is True


def test_an_invite_is_accepted_although_the_invitee_belongs_to_no_firm_yet(db):
    from routers.identity import accept_invite, AcceptInviteBody
    from datetime import datetime, timedelta, timezone

    db.rows.append({"id": "invitee", "firm_id": F1, "email": "inv@one.test", "role": "Manager",
                    "status": "invited", "auth_user_id": None, "deleted_at": None,
                    "invite_token": "tok-256",
                    "invite_expires_at": (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()})

    out = accept_invite(AcceptInviteBody(token="tok-256"),
                        jwt_user={"auth_user_id": "auth-inv", "email": "inv@one.test"})

    assert out["data"]["firm_id"] == F1
    assert _row(db, "invitee")["auth_user_id"] == "auth-inv"
    assert _row(db, "invitee")["invite_token"] is None


def test_an_approved_role_change_cannot_reach_another_firms_user(db):
    """The handler takes user_id off a request payload. Before the repository
    carried the firm, this updated whichever row had that id."""
    from services.approval_service import _h_role_change, _h_user_activation

    assert _h_role_change(F1, {"user_id": "stranger", "role": "Partner"}) == {}
    assert _h_user_activation(F1, {"user_id": "stranger", "is_active": False}) == {}
    assert _row(db, "stranger")["role"] == "Executive"
    assert _row(db, "stranger")["is_active"] is True

    assert _h_role_change(F1, {"user_id": "colleague", "role": "Manager"})["role"] == "Manager"


def test_a_task_can_be_assigned_to_a_colleague(db):
    """routers/tasks' C4 check reads the assignee's row. Through the caller's
    own client it could only ever see the caller, so assigning anybody else
    answered 'Assignee not found in this firm'."""
    assert user_repo.find_by_id("colleague", firm_id=F1)["id"] == "colleague"
    assert user_repo.find_by_id("stranger", firm_id=F1) is None


def test_every_id_addressed_method_requires_the_firm(db):
    with pytest.raises(TypeError):
        user_repo.find_by_id("me")
    with pytest.raises(TypeError):
        user_repo.update("me", {"role": "Partner"})
    with pytest.raises(TypeError):
        user_repo.find_by_email("me@one.test")
    with pytest.raises(ValueError):
        user_repo.find_all()
    with pytest.raises(ValueError):
        user_repo.create({"full_name": "No Firm", "email": "x@y"})
    with pytest.raises(ValueError):
        user_repo.update("me", {"firm_id": F2}, firm_id=F1)
