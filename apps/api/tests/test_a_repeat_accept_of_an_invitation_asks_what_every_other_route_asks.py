"""The repeat-accept answer of an invitation asks what every other route asks (POST-A-498).

WHAT WAS WRONG. A person who has joined and presses the invitation's link again is answered with their own membership (POST-A-481), and the route that
does it authenticates with the token alone, because a caller who is accepting an invitation may have no member row yet. `_already_joined` therefore read
the caller's membership with the token's own `sub` and asked none of the refusals `get_current_user` makes for every route behind it. A member whose
sessions had all been signed out (a suspension, a force sign-out), whose session had been signed out from another device, or whose firm was suspended or
deleted, calling it with any token string, was handed their own firm id, role and name instead of the refusal any other route gives. Their own data only,
never another person's, which is why it was found by an independent review and not by a failure.

WHAT IT DOES. `core/auth._refuse_an_ended_session` holds the four refusals once, `get_current_user` asks it, and `refuse_a_member_whose_session_has_ended`
reads the member and their firm as `get_current_user` does and asks it for the one route that has no dependency. These tests send the SAME rows and the
SAME token to both doors and hold the answers equal, status and words, so the second door cannot drift from the first.

NOT ASKED, ON PURPOSE: the second-factor level. The answer is the caller's own membership, which `/me` gives at the first level too (the browser has to
read it to know it must enrol a second factor).
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

import core.auth as auth
import routers.identity as idmod
from core.auth import get_jwt_user

NOW = 1_800_000_000
REVOKED = NOW - 1_000                     # every session of the member ended 1,000 s ago
OTHERS = NOW - 1_000                      # the member signed out their other sessions 1,000 s ago
KEPT = "sess-kept"
AUTH_ID = "auth-member-1"
EMAIL = "member@firm.test"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _token(iat: float, began: float, session_id: str | None = "sess-x", **more) -> dict:
    out = {"sub": AUTH_ID, "email": EMAIL, "iat": iat, "amr": [{"method": "password", "timestamp": began}], **more}
    if session_id is not None:
        out["session_id"] = session_id
    return out


LIVE_NEW = _token(NOW, NOW - 10)                                   # signed in after any mark
OLD_BEFORE = _token(REVOKED - 500, REVOKED - 600)                  # issued and began before the marks
RENEWED = _token(NOW, REVOKED - 600)                               # a renewed token of an old session: new iat, old stamp
KEPT_RENEWED = _token(NOW, REVOKED - 600, session_id=KEPT)         # the session that asked to stay, renewed


class _Repo:
    """What the route reads of the member: the membership row, found by the sign-in's own id."""
    def __init__(self, linked=True):
        self.row = {"id": "u1", "firm_id": "F1", "role": "Manager", "full_name": "Member One", "email": EMAIL, "is_active": True,
                    "auth_user_id": AUTH_ID, "status": "active"}
        self.linked = linked
        self.token_lookups = 0

    def find_by_invite_token(self, token):
        self.token_lookups += 1
        return None                                                  # the token is spent or never existed: the repeat path

    def find_linked_member(self, auth_user_id):
        return self.row if self.linked and auth_user_id == AUTH_ID else None

    def find_by_id(self, uid, *, firm_id):
        return self.row if uid == self.row["id"] and firm_id == self.row["firm_id"] else None


@pytest.fixture()
def world(monkeypatch):
    repo = _Repo()
    monkeypatch.setattr(idmod, "user_repo", repo)
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setattr(auth, "get_service_supabase", lambda: object())
    state = {"user": {"id": "u1", "firm_id": "F1", "role": "Manager", "full_name": "Member One", "is_active": True},
             "firm": {"is_active": True, "deleted_at": None}, "lookups": 0}

    def _lookup(_supabase, auth_user_id):
        state["lookups"] += 1
        return (dict(state["user"]), dict(state["firm"])) if auth_user_id == AUTH_ID else (None, None)

    monkeypatch.setattr(auth, "_get_user_and_firm", _lookup)
    state["repo"] = repo
    return state


def _repeat_accept(claims: dict | None, token: dict | None = None, auth_user_id: str = AUTH_ID, email: str = EMAIL):
    """The repeat of accept-invite as the browser sends it: any token string, and the verified sign-in's own claims."""
    app = FastAPI()
    app.include_router(idmod.invite_router)
    jwt_user = {"auth_user_id": auth_user_id, "email": email, "aal": "aal1"}
    if claims is not None:
        jwt_user["session_claims"] = claims
    app.dependency_overrides[get_jwt_user] = lambda: jwt_user
    r = TestClient(app, raise_server_exceptions=False).post("/api/identity/accept-invite", json={"token": "any-spent-token"})
    return r


def _claims_of(token: dict) -> dict:
    return {k: token[k] for k in ("iat", "amr", "session_id") if k in token}


def _through_the_ordinary_door(token: dict):
    """The same rows and the same token through `get_current_user`, which every other route sits behind: its refusal as (status, detail)."""
    from unittest import mock
    with mock.patch.object(auth, "decode_supabase_jwt", lambda t: token):
        try:
            auth.get_current_user(authorization="Bearer t")
        except HTTPException as refused:
            return refused.status_code, refused.detail
    return 200, None


# ── the fixed cases, each said in a sentence ─────────────────────────────────────────────────────────────────────────────────

def test_a_member_in_good_standing_is_still_told_they_have_joined(world):
    r = _repeat_accept(_claims_of(LIVE_NEW))
    assert r.status_code == 200
    assert r.json()["data"] == {"firm_id": "F1", "role": "Manager", "full_name": "Member One", "already_joined": True}


def test_a_member_whose_sessions_were_all_signed_out_is_refused_and_told_nothing(world):
    world["user"]["sessions_revoked_at"] = _iso(REVOKED)
    r = _repeat_accept(_claims_of(OLD_BEFORE))
    assert r.status_code == 401 and r.json()["detail"] == "Session revoked. Please sign in again."
    assert "firm_id" not in r.text and "Manager" not in r.text and "Member One" not in r.text, "the refusal carried the membership"


def test_a_renewed_token_of_a_signed_out_session_is_refused_too(world):
    world["user"]["sessions_revoked_at"] = _iso(REVOKED)
    assert _repeat_accept(_claims_of(RENEWED)).status_code == 401


def test_a_new_sign_in_after_the_revocation_is_answered(world):
    world["user"]["sessions_revoked_at"] = _iso(REVOKED)
    assert _repeat_accept(_claims_of(LIVE_NEW)).status_code == 200


def test_a_session_signed_out_from_another_device_is_refused_and_the_kept_one_is_not(world):
    world["user"]["other_sessions_revoked_at"] = _iso(OTHERS)
    world["user"]["other_sessions_kept_session_id"] = KEPT
    other = _repeat_accept(_claims_of(RENEWED))
    assert other.status_code == 401 and "signed out from another device" in other.json()["detail"]
    assert _repeat_accept(_claims_of(KEPT_RENEWED)).status_code == 200


@pytest.mark.parametrize("firm,detail", [({"is_active": True, "deleted_at": "2026-11-01T00:00:00+00:00"}, "Firm unavailable"),
                                        ({"is_active": False, "deleted_at": None}, "Firm suspended")])
def test_a_member_of_a_deleted_or_suspended_firm_is_refused(world, firm, detail):
    world["firm"].update(firm)
    r = _repeat_accept(_claims_of(LIVE_NEW))
    assert r.status_code == 403 and r.json()["detail"] == detail


def test_a_disabled_account_is_refused_in_the_ordinary_words(world):
    world["user"]["is_active"] = False
    r = _repeat_accept(_claims_of(LIVE_NEW))
    assert r.status_code == 403 and r.json()["detail"].startswith("Account disabled")


def test_a_revocation_nobody_can_read_refuses_the_request_and_is_not_skipped(world):
    world["user"]["sessions_revoked_at"] = "not a time"
    r = _repeat_accept(_claims_of(LIVE_NEW))
    assert r.status_code == 401 and "could not be verified" in r.json()["detail"]


def test_a_token_that_shows_nothing_cannot_pass_a_revocation(world):
    world["user"]["sessions_revoked_at"] = _iso(REVOKED)
    assert _repeat_accept({}).status_code == 401, "no session claims read as a session that began before the revocation, which is the safe way round"
    assert _repeat_accept(None).status_code == 401


def test_with_no_mark_a_token_that_shows_nothing_is_still_answered(world):
    assert _repeat_accept({}).status_code == 200


def test_a_sign_in_that_is_not_a_member_is_asked_nothing_and_is_refused_as_before(world):
    world["repo"].linked = False
    r = _repeat_accept(_claims_of(LIVE_NEW))
    assert r.status_code == 404
    assert world["lookups"] == 0, "a stranger's request cost a member lookup"


def test_a_member_row_that_is_not_the_callers_address_is_not_answered_and_is_not_asked_about(world):
    r = _repeat_accept(_claims_of(LIVE_NEW), email="somebody-else@firm.test")
    assert r.status_code == 404 and world["lookups"] == 0


def test_an_address_with_no_member_row_is_refused_nothing_by_the_function_itself(world):
    """Reached through the route, a sign-in that is not a member never gets this far (it has no membership to answer). The function is also
    the one other doors may ask, so it holds its own rule: no member row, no refusal, and no lookup of a firm."""
    assert auth.refuse_a_member_whose_session_has_ended("nobody-at-all", _claims_of(OLD_BEFORE)) is None
    assert auth.refuse_a_member_whose_session_has_ended("nobody-at-all", {}) is None
    assert world["lookups"] == 2, "the member lookup is the one read it makes"


def test_the_development_fallback_asks_nothing_because_there_is_no_member_table(world, monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    world["user"]["sessions_revoked_at"] = _iso(REVOKED)
    assert _repeat_accept(_claims_of(OLD_BEFORE)).status_code == 200
    assert world["lookups"] == 0


# ── the two doors say the same thing, from one table ─────────────────────────────────────────────────────────────────────────

CASES = [
    ("a good standing", {}, {}, LIVE_NEW),
    ("every session signed out, an old token", {"sessions_revoked_at": _iso(REVOKED)}, {}, OLD_BEFORE),
    ("every session signed out, a renewed token", {"sessions_revoked_at": _iso(REVOKED)}, {}, RENEWED),
    ("every session signed out, a sign-in after it", {"sessions_revoked_at": _iso(REVOKED)}, {}, LIVE_NEW),
    ("an unreadable revocation", {"sessions_revoked_at": "garbage"}, {}, LIVE_NEW),
    ("other sessions signed out, another session", {"other_sessions_revoked_at": _iso(OTHERS), "other_sessions_kept_session_id": KEPT}, {}, RENEWED),
    ("other sessions signed out, the kept session", {"other_sessions_revoked_at": _iso(OTHERS), "other_sessions_kept_session_id": KEPT}, {}, KEPT_RENEWED),
    ("other sessions signed out, a sign-in after it", {"other_sessions_revoked_at": _iso(OTHERS), "other_sessions_kept_session_id": KEPT}, {}, LIVE_NEW),
    ("both marks, the kept session", {"sessions_revoked_at": _iso(REVOKED), "other_sessions_revoked_at": _iso(OTHERS),
                                      "other_sessions_kept_session_id": KEPT}, {}, KEPT_RENEWED),
    ("a deleted firm", {}, {"deleted_at": "2026-11-01T00:00:00+00:00"}, LIVE_NEW),
    ("a suspended firm", {}, {"is_active": False}, LIVE_NEW),
    ("a disabled account", {"is_active": False}, {}, LIVE_NEW),
    ("a disabled account in a suspended firm", {"is_active": False}, {"is_active": False}, LIVE_NEW),
]


@pytest.mark.parametrize("why,user_extra,firm_extra,token", CASES, ids=[c[0] for c in CASES])
def test_the_repeat_accept_answers_what_get_current_user_answers(world, why, user_extra, firm_extra, token):
    world["user"].update(user_extra)
    world["firm"].update(firm_extra)
    ordinary_status, ordinary_detail = _through_the_ordinary_door(token)
    r = _repeat_accept(_claims_of(token))
    if ordinary_status == 200:
        assert r.status_code == 200, f"{why}: the ordinary door admits and the repeat-accept refused with {r.status_code} {r.text}"
    else:
        assert (r.status_code, r.json()["detail"]) == (ordinary_status, ordinary_detail), (
            f"{why}: the ordinary door says {ordinary_status} {ordinary_detail!r}, the repeat-accept says {r.status_code} {r.text}")


# ── the shape of the change ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_get_jwt_user_hands_over_the_session_claims_and_nothing_else_of_the_token(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://project.supabase.test")
    monkeypatch.setattr(auth, "decode_supabase_jwt", lambda t: {
        "sub": "u1", "email": "a@b.test", "aal": "aal1", "iat": 5, "exp": 9, "role": "authenticated", "phone": "+9199",
        "amr": [{"method": "password", "timestamp": 4}], "session_id": "s-1", "user_metadata": {"x": 1}})
    got = auth.get_jwt_user("Bearer t")
    assert got["session_claims"] == {"iat": 5, "amr": [{"method": "password", "timestamp": 4}], "session_id": "s-1"}
    assert "phone" not in str(got) and "user_metadata" not in str(got), "more of the token than the session rules read left the dependency"
    monkeypatch.setattr(auth, "decode_supabase_jwt", lambda t: {"sub": "u1"})
    assert auth.get_jwt_user("Bearer t")["session_claims"] == {}


def test_get_current_user_asks_the_shared_function_and_holds_none_of_the_four_refusals_itself():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(auth.__file__).read_text(encoding="utf-8"))
    fns = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    called = lambda fn: {c.func.id for c in ast.walk(fns[fn]) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}   # noqa: E731
    assert "_refuse_an_ended_session" in called("get_current_user")
    assert "_refuse_an_ended_session" in called("refuse_a_member_whose_session_has_ended")
    assert "_refuse_a_session_signed_out_from_elsewhere" in called("_refuse_an_ended_session")
    src = Path(auth.__file__).read_text(encoding="utf-8")
    body = src.split("def get_current_user(")[1].split("def get_jwt_user(")[0]
    for sentence in ("Account disabled", "Firm unavailable", "Firm suspended", "Session revoked"):
        assert sentence not in body, f"get_current_user holds {sentence!r} itself again: the refusal has two homes"


def test_the_route_asks_for_the_refusal_after_it_knows_the_caller_is_that_member():
    import ast
    from pathlib import Path
    tree = ast.parse(Path(idmod.__file__).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_already_joined")
    names = [c.func.id for c in ast.walk(fn) if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)]
    assert "refuse_a_member_whose_session_has_ended" in names
    src = ast.get_source_segment(Path(idmod.__file__).read_text(encoding="utf-8"), fn)
    assert src.index("refuse_a_member_whose_session_has_ended") > src.index("!= (jwt_user.get(\"email\")"), "the lookup is made for a caller who is not that member"
    assert src.index("refuse_a_member_whose_session_has_ended") < src.index('"already_joined": True'), "the membership is returned before the refusal is asked"
