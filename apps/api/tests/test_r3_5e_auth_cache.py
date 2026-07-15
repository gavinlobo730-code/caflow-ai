"""
R3.5e — proves core/auth.py's get_current_user() caching fix.

Before this fix: every request with a real Supabase JWT did 2 serialized,
uncached DB round trips (users, firms) — on ~88/93 routers, every single
request. This proves a short-TTL in-process cache now avoids repeating
those lookups within the TTL window, while never caching a failed lookup
(so a legitimate new user mid-onboarding is never stuck behind a stale 403).
"""
import time

import pytest
from fastapi import HTTPException

import core.auth as auth


class _Res:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, counters, table, row):
        self._counters = counters
        self._table = table
        self._row = row

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def single(self):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        self._counters[self._table] = self._counters.get(self._table, 0) + 1
        return _Res(self._row)


class _CountingSupabase:
    """Tracks how many times each table was queried."""
    def __init__(self, users_row, firm_row):
        self.calls: dict[str, int] = {}
        self._users_row = users_row
        self._firm_row = firm_row

    def table(self, name):
        row = self._users_row if name == "users" else self._firm_row
        return _Q(self.calls, name, row)


def _patch(monkeypatch, users_row, firm_row, sub="counting-user"):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")

    class _K:
        key = "k"

    class _J:
        def get_signing_key_from_jwt(self, _t):
            return _K()

    monkeypatch.setattr(auth, "_get_jwks_client", lambda: _J())
    monkeypatch.setattr(auth.jwt, "decode", lambda *a, **k: {"sub": sub, "iat": 100, "email": "e@f"})
    db = _CountingSupabase(users_row, firm_row)
    monkeypatch.setattr(auth, "get_service_supabase", lambda: db)
    monkeypatch.setattr(auth, "_user_lookup_cache", {})
    return db


ACTIVE_USER = {"id": "u1", "firm_id": "F1", "role": "Partner", "is_active": True}
ACTIVE_FIRM = {"is_active": True, "deleted_at": None}


def test_second_call_within_ttl_skips_both_db_lookups(monkeypatch):
    db = _patch(monkeypatch, ACTIVE_USER, ACTIVE_FIRM)

    auth.get_current_user(authorization="Bearer x")
    auth.get_current_user(authorization="Bearer x")

    assert db.calls["users"] == 1, "second call should have been served from cache"
    assert db.calls["firms"] == 1


def test_different_users_get_independent_cache_entries(monkeypatch):
    db = _patch(monkeypatch, ACTIVE_USER, ACTIVE_FIRM, sub="user-a")
    auth.get_current_user(authorization="Bearer x")

    # A different auth_user_id must not reuse user-a's cache slot.
    monkeypatch.setattr(auth.jwt, "decode", lambda *a, **k: {"sub": "user-b", "iat": 100, "email": "e@f"})
    auth.get_current_user(authorization="Bearer x")

    assert db.calls["users"] == 2


def test_expired_cache_entry_triggers_fresh_lookup(monkeypatch):
    db = _patch(monkeypatch, ACTIVE_USER, ACTIVE_FIRM)

    real_monotonic = time.monotonic
    fake_now = {"t": real_monotonic()}
    monkeypatch.setattr(auth.time, "monotonic", lambda: fake_now["t"])

    auth.get_current_user(authorization="Bearer x")
    assert db.calls["users"] == 1

    # Still within TTL — cached.
    fake_now["t"] += auth._USER_LOOKUP_CACHE_TTL_SECONDS - 1
    auth.get_current_user(authorization="Bearer x")
    assert db.calls["users"] == 1

    # Past TTL — fresh lookup.
    fake_now["t"] += 5
    auth.get_current_user(authorization="Bearer x")
    assert db.calls["users"] == 2


def test_failed_lookup_is_never_cached(monkeypatch):
    """A user row that doesn't exist yet (e.g. mid-onboarding) must not be
    cached — otherwise a legitimate new user would be stuck behind a stale
    403 for the whole TTL window."""
    db = _patch(monkeypatch, None, None)

    with pytest.raises(HTTPException) as e1:
        auth.get_current_user(authorization="Bearer x")
    assert e1.value.status_code == 403

    with pytest.raises(HTTPException):
        auth.get_current_user(authorization="Bearer x")

    assert db.calls["users"] == 2, "a not-found user must never be cached"
