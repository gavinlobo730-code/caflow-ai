"""A closed firm's people are signed out, and a token the browser renews does not walk back in (POST-A-482, POST-A-484).

What was wrong (read in the code on 19-11-2026, after the owner's live testing of 18-11-2026)
    1. The platform page's suspend, soft delete and purge only flipped `firms.is_active` / `deleted_at`, so the firm's
       people held live sessions on screens the API now refused.
    2. Even where a revocation WAS stamped (the Team area's force sign-out), `core/auth` compared the token's `iat`
       alone, and a browser renews its token whenever a call answers 401: the renewed token's `iat` is after the
       revocation, so the person was back in. A revocation has to ask when the person last PROVED who they are
       (`core/auth_time`, the oldest `amr` stamp, which a renewed token carries unchanged).
    3. `require_platform_admin_mfa` checked that the token said `aal2`, which stays true for the session's whole life.
       It now needs an authenticator code entered in the last five minutes.
"""
import time
from datetime import datetime

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import core.auth as auth
import core.auth_time as at
import core.platform_auth as pa
import routers.platform as plat
from core.auth import get_jwt_user

NOW = 1_800_000_000.0


def _token(iat, *amr):
    return {"iat": iat, "amr": [{"method": m, "timestamp": ts} for m, ts in amr]}


# ── the clock: iat versus the last proof ─────────────────────────────────────

def test_a_token_issued_before_the_revocation_is_refused_as_ever():
    assert at.issued_before_revocation(_token(NOW - 10, ("password", NOW - 10)), NOW) is True


def test_a_RENEWED_token_is_refused_because_it_carries_the_old_proof():
    # signed in at NOW-3600, revoked at NOW, the browser renewed the token at NOW+5: the new iat is after the revocation.
    renewed = _token(NOW + 5, ("password", NOW - 3600))
    assert float(renewed["iat"]) > NOW
    assert at.issued_before_revocation(renewed, NOW) is True


def test_a_NEW_sign_in_after_the_revocation_is_accepted():
    assert at.issued_before_revocation(_token(NOW + 30, ("password", NOW + 30)), NOW) is False


def test_a_code_entered_after_the_revocation_does_not_bring_an_old_session_back():
    # The independent review's case: the person's sessions were revoked at NOW; they still hold the old session and enter an
    # authenticator code against it. The password stamp is from before, the code's is after: the SESSION began before the
    # revocation, so it stays refused.
    assert at.issued_before_revocation(_token(NOW + 60, ("password", NOW - 600), ("totp", NOW + 50)), NOW) is True


def test_a_new_sign_in_with_a_code_after_the_revocation_is_accepted():
    assert at.issued_before_revocation(_token(NOW + 60, ("password", NOW + 20), ("totp", NOW + 50)), NOW) is False


def test_a_token_with_no_amr_is_judged_by_iat_alone():
    assert at.issued_before_revocation({"iat": NOW + 1}, NOW) is False
    assert at.issued_before_revocation({"iat": NOW - 1}, NOW) is True
    assert at.issued_before_revocation({"iat": NOW + 1, "amr": "password"}, NOW) is False
    assert at.issued_before_revocation({"iat": NOW + 1, "amr": [{"method": "password"}, "x", None]}, NOW) is False


def test_stamps_that_are_not_numbers_are_ignored_and_never_read_as_zero():
    payload = {"iat": NOW + 1, "amr": [{"method": "password", "timestamp": True}, {"method": "totp", "timestamp": "2026"}]}
    assert at.session_began_epoch(payload) is None
    assert at.issued_before_revocation(payload, NOW) is False


def test_core_auth_uses_the_clock_not_iat_alone():
    assert auth._token_predates_revocation(_token(NOW + 5, ("password", NOW - 3600)), NOW) is True
    assert auth._token_predates_revocation(_token(NOW + 5, ("password", NOW + 5)), NOW) is False
    src = open(auth.__file__, encoding="utf-8").read()
    assert 'float(payload["iat"]) < revoked_epoch' not in src, "the revocation compares iat alone again"


# ── the fresh authenticator code ──────────────────────────────────────────────

def test_a_code_is_fresh_for_five_minutes_and_not_after():
    assert at.authenticator_code_is_fresh(NOW - 10, NOW) is True
    assert at.authenticator_code_is_fresh(NOW - 300, NOW) is True
    assert at.authenticator_code_is_fresh(NOW - 301, NOW) is False
    assert at.authenticator_code_is_fresh(None, NOW) is False
    # a little ahead is clock skew; a long way ahead is not a code
    assert at.authenticator_code_is_fresh(NOW + 30, NOW) is True
    assert at.authenticator_code_is_fresh(NOW + 3600, NOW) is False


def test_get_jwt_user_reports_when_the_last_code_was_entered(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.setattr(auth, "decode_supabase_jwt", lambda token: {
        "sub": "u1", "email": "a@b.test", "aal": "aal2",
        "amr": [{"method": "password", "timestamp": 100}, {"method": "totp", "timestamp": 250}, {"method": "totp", "timestamp": 200}],
    })
    got = auth.get_jwt_user("Bearer t")
    assert got["last_authenticator_code_at"] == 250.0 and got["aal"] == "aal2"
    monkeypatch.setattr(auth, "decode_supabase_jwt", lambda token: {"sub": "u1", "aal": "aal1"})
    assert auth.get_jwt_user("Bearer t")["last_authenticator_code_at"] is None


# ── the platform actions ──────────────────────────────────────────────────────

class _Rows:
    def __init__(self, data): self.data = data


class _Query:
    def __init__(self, db, table): self.db, self.table_name = db, table; self._eq = {}; self._update = None; self._single = False
    def select(self, *a, **k): return self
    def eq(self, col, val): self._eq[col] = val; return self
    def maybe_single(self): self._single = True; return self
    def insert(self, row): self.db.inserted.append((self.table_name, row)); return self
    def update(self, change): self._update = change; return self
    def execute(self):
        if self._update is not None:
            self.db.updates.append((self.table_name, dict(self._update), dict(self._eq)))
            if self.table_name == "users":
                return _Rows([{"id": "m1"}, {"id": "m2"}])
            return _Rows([{"id": "FIRM-1"}])
        if self.table_name == "firms":
            return _Rows({"id": "FIRM-1", "name": "Acme & Co", "is_active": True, "deleted_at": None})
        return _Rows(None)


class _DB:
    def __init__(self): self.updates, self.inserted, self.rpc_calls, self.order = [], [], [], []
    def table(self, name): return _Query(self, name)
    def rpc(self, fn, params):
        self.rpc_calls.append((fn, params))
        self.order.append(("rpc", len(self.updates)))
        class _R:
            def execute(_s): return _Rows({"clients_deleted": 0, "users_deleted": 2})
        return _R()


def _client(monkeypatch, *, code_age=0.0, aal="aal2"):
    db = _DB()
    monkeypatch.setattr(pa, "_is_platform_admin", lambda uid: True)
    monkeypatch.setattr(plat, "get_service_supabase", lambda: db)
    monkeypatch.setattr(plat, "log_event", lambda *a, **k: None)
    app = FastAPI()
    app.include_router(plat.router)
    stamp = None if code_age is None else time.time() - code_age
    app.dependency_overrides[get_jwt_user] = lambda: {
        "auth_user_id": "u1", "email": "x@y.z", "aal": aal, "last_authenticator_code_at": stamp}
    return TestClient(app, raise_server_exceptions=False), db


def _revocations(db):
    return [(t, ch, eq) for t, ch, eq in db.updates if t == "users" and "sessions_revoked_at" in ch]


def test_suspending_a_firm_signs_out_every_member_of_that_firm_only(monkeypatch):
    c, db = _client(monkeypatch)
    r = c.post("/api/platform/firms/FIRM-1/suspend", json={"reason": "non-payment"})
    assert r.status_code == 200 and r.json()["data"]["sessions_ended"] == 2
    rev = _revocations(db)
    assert len(rev) == 1 and rev[0][2] == {"firm_id": "FIRM-1"}, "naming the firm is the scope"
    datetime.fromisoformat(rev[0][1]["sessions_revoked_at"])           # a readable instant


def test_soft_deleting_a_firm_signs_out_its_members(monkeypatch):
    c, db = _client(monkeypatch)
    r = c.delete("/api/platform/firms/FIRM-1")
    assert r.status_code == 200 and r.json()["data"]["sessions_ended"] == 2
    assert len(_revocations(db)) == 1


def test_purging_a_firm_stamps_nothing_and_claims_nothing(monkeypatch):
    # The independent review's finding: the purge deletes the member rows a stamp would live on, and the sign-in accounts stay,
    # so no stamp can end a purged member's session. The route no longer pretends to (POST-A-499 records the gap).
    c, db = _client(monkeypatch)
    r = c.delete("/api/platform/firms/FIRM-1/permanent")
    assert r.status_code == 200 and "sessions_ended" not in r.json()["data"]
    assert _revocations(db) == []
    assert db.inserted and "sessions_ended" not in db.inserted[0][1]["metadata"]


@pytest.mark.parametrize("verb,path", [("post", "/api/platform/firms/FIRM-1/suspend"), ("delete", "/api/platform/firms/FIRM-1")])
def test_the_sessions_are_ended_before_the_firm_is_closed(monkeypatch, verb, path):
    c, db = _client(monkeypatch)
    r = getattr(c, verb)(path, json={"reason": "x"}) if verb == "post" else c.delete(path)
    assert r.status_code == 200
    tables = [t for t, _ch, _eq in db.updates]
    assert tables.index("users") < tables.index("firms"), "the stamp comes first, so a failed stamp leaves the firm open"


@pytest.mark.parametrize("verb,path", [("post", "/api/platform/firms/FIRM-1/suspend"), ("delete", "/api/platform/firms/FIRM-1")])
def test_a_stamp_that_fails_leaves_the_firm_open_and_the_request_refused(monkeypatch, verb, path):
    c, db = _client(monkeypatch)
    real = _Query.execute
    def failing(self):
        if self._update is not None and self.table_name == "users":
            raise RuntimeError("write refused")
        return real(self)
    monkeypatch.setattr(_Query, "execute", failing)
    r = c.post(path, json={"reason": "x"}) if verb == "post" else c.delete(path)
    assert r.status_code == 500
    assert [t for t, _ch, _eq in db.updates if t == "firms"] == [], "the firm was closed although its people stayed signed in"


def test_unsuspending_does_not_touch_anybody_s_sessions(monkeypatch):
    c, db = _client(monkeypatch)
    r = c.post("/api/platform/firms/FIRM-1/unsuspend")
    assert r.status_code == 200
    assert _revocations(db) == [], "a person signed out by the suspension signs in again; nothing restores the old session"


# ── the fresh code on the three destructive actions ───────────────────────────

_ACTIONS = [("post", "/api/platform/firms/FIRM-1/suspend", {"reason": "x"}),
            ("delete", "/api/platform/firms/FIRM-1", None),
            ("delete", "/api/platform/firms/FIRM-1/permanent", None)]


@pytest.mark.parametrize("verb,path,body", _ACTIONS)
def test_a_code_older_than_five_minutes_is_refused_with_the_sentence_the_page_recognises(monkeypatch, verb, path, body):
    c, db = _client(monkeypatch, code_age=301)
    r = getattr(c, verb)(path, **({"json": body} if body else {}))
    assert r.status_code == 403 and r.json()["detail"] == at.FRESH_CODE_SENTENCE
    assert db.updates == [] and db.rpc_calls == [], "nothing was changed"


@pytest.mark.parametrize("verb,path,body", _ACTIONS)
def test_no_code_at_all_is_refused_too(monkeypatch, verb, path, body):
    c, _ = _client(monkeypatch, code_age=None)
    r = getattr(c, verb)(path, **({"json": body} if body else {}))
    assert r.status_code == 403 and r.json()["detail"] == at.FRESH_CODE_SENTENCE


@pytest.mark.parametrize("verb,path,body", _ACTIONS)
def test_a_code_entered_a_minute_ago_is_enough(monkeypatch, verb, path, body):
    c, _ = _client(monkeypatch, code_age=60)
    r = getattr(c, verb)(path, **({"json": body} if body else {}))
    assert r.status_code == 200


def test_without_the_second_factor_at_all_the_older_sentence_still_comes_first(monkeypatch):
    c, _ = _client(monkeypatch, code_age=0, aal="aal1")
    r = c.delete("/api/platform/firms/FIRM-1")
    assert r.status_code == 403 and "Multi-factor" in r.json()["detail"]


def test_the_router_no_longer_says_there_is_no_hard_delete():
    src = open(plat.__file__, encoding="utf-8").read()
    assert "No billing, impersonation, hard delete" not in src
    assert "permanent" in src.split('"""')[1].lower()
