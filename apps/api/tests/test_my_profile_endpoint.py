"""
PATCH /api/identity/me — a staff member changing their own display name.

WHY IT EXISTS
    The Settings page used to do this itself: supabase.from("users").update({
    full_name }). Migration 153 revoked UPDATE on `users` from the
    `authenticated` role, so that call has answered "permission denied for table
    users" ever since. The revoke was right — a browser should not be able to
    write user rows — but nothing replaced the write, so nobody could change
    their own name.

THE PROPERTY THAT MATTERS
    There is no user_id parameter. The row is addressed from the verified token,
    so this endpoint CANNOT edit anyone else's profile — not through a crafted
    body, not through a forgotten scope check, because there is no id to
    substitute. The tests below pin that shape, not just the happy path.
"""
import pytest

from core.permissions import can
from repositories.user_repository import user_repo
from routers.identity import update_my_profile


FIRM = "firm-1"
ME = "user-me"


class Body:
    def __init__(self, full_name):
        self.full_name = full_name


@pytest.fixture
def captured(monkeypatch):
    """Record what reaches user_repo.update without touching a database."""
    calls = []

    def fake_update(user_id, patch):
        calls.append((user_id, patch))
        return {"id": user_id, **patch}

    monkeypatch.setattr(user_repo, "update", fake_update)
    monkeypatch.setattr("routers.identity.log_event", lambda *a, **k: None)
    return calls


def _me(role="Executive"):
    return {"id": ME, "firm_id": FIRM, "email": "me@firm.com", "role": role}


def test_the_name_is_written_to_the_callers_own_row(captured):
    body = update_my_profile(Body("Asha Menon"), current_user=_me())

    assert captured == [(ME, {"full_name": "Asha Menon"})]
    assert body["success"] is True


def test_only_full_name_is_writable(captured):
    """The patch is built here, not taken from the request, so a body carrying
    role or firm_id cannot smuggle a privilege escalation through."""
    update_my_profile(Body("Asha"), current_user=_me())

    _, patch = captured[0]
    assert set(patch) == {"full_name"}


def test_surrounding_whitespace_is_trimmed(captured):
    update_my_profile(Body("   Asha Menon  "), current_user=_me())

    assert captured[0][1]["full_name"] == "Asha Menon"


@pytest.mark.parametrize("bad", ["", "   ", "\t\n"])
def test_an_empty_name_is_refused(captured, bad):
    """Whitespace-only must be refused too — otherwise the trim above turns it
    into an empty display name that renders as a blank row in the team list."""
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        update_my_profile(Body(bad), current_user=_me())

    assert exc.value.status_code == 400
    assert not captured


def test_an_absurdly_long_name_is_refused(captured):
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        update_my_profile(Body("x" * 121), current_user=_me())

    assert exc.value.status_code == 400
    assert not captured


def test_a_name_at_the_limit_is_accepted(captured):
    """Boundary in the allowed direction — an off-by-one here would reject a
    legitimate name and look like an unrelated failure."""
    update_my_profile(Body("x" * 120), current_user=_me())

    assert captured[0][1]["full_name"] == "x" * 120


def test_the_endpoint_takes_no_user_id(captured):
    """The whole safety argument. If someone later adds a user_id parameter,
    this endpoint becomes an unguarded way to rename any colleague and the
    'no scope check needed' reasoning in its docstring stops being true."""
    import inspect

    params = set(inspect.signature(update_my_profile).parameters)

    assert params == {"body", "current_user"}


def test_every_staff_role_may_edit_their_own_name():
    """identity:write is _ALL_STAFF. A Reviewer has to be able to set their own
    display name — this is self-service telemetry-grade, not a privilege."""
    for role in ("Partner", "Manager", "Executive", "Reviewer"):
        assert can(role, "identity", "write") is True, role


def test_it_is_not_guarded_by_team_write():
    """team:write is Partner-only and governs editing OTHER people's accounts.
    Reusing it here would have left everyone below Partner still unable to
    change their own name — the original bug, differently caused."""
    import inspect

    dep = inspect.signature(update_my_profile).parameters["current_user"].default

    assert getattr(dep.dependency, "__name__", "") == "rbac_identity_write"


@pytest.mark.parametrize("role", ["Manager", "Executive", "Reviewer"])
def test_non_partners_are_not_locked_out(role, captured):
    """Guards the regression the old code had: a Reviewer must get through."""
    update_my_profile(Body("Someone"), current_user=_me(role))

    assert captured[0][0] == ME
