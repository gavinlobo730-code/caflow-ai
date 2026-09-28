"""
A client's additional GST registrations are WRITTEN through the service role,
and only ever for the client the caller was authorised for.

WHAT WAS WRONG
    Under USE_USER_JWT a request runs as `authenticated`, which holds only
    SELECT on client_gst_registrations and whose one permissive policy is a
    SELECT. So add, close and withdraw all failed as 42501 — a registration
    could be listed and never recorded.

    Moving the writes to the service role takes RLS out from between the caller
    and the row, and close()/withdraw() matched the row on id and firm alone.
    The router asserts access to the client_id in the REQUEST; nothing tied the
    registration id to that client. An Executive assigned to client A could
    send A's id beside client B's registration id and close B's registration.
    So the client travels into the service and is part of every match.

WHAT IS ASSERTED — by calling the code
    * the three routes hand the service a SERVICE client, never the per-request
      one, and pass the asserted client through;
    * close() and withdraw() refuse, as a 404, a registration belonging to a
      different client of the same firm, and leave it untouched;
    * both still work for the registration's own client.
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

import core.supabase_client as sc
import services.audit_service as audit
from routers import client_gst_registrations as router
from services import client_gst_registration_service as svc

CALLER = {"firm_id": "F1", "id": "u1", "auth_user_id": "a1",
          "email": "ca@f.test", "role": "Partner"}


# ── A fake that applies filters to writes as well as reads ─────────────────

class _Q:
    def __init__(self, store, table):
        self._store, self._table = store, table
        self._filters: list = []
        self._patch = None
        self._limit = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col, val):
        self._filters.append(lambda r, c=col, v=val: r.get(c) == v)
        return self

    def is_(self, col, _null):
        self._filters.append(lambda r, c=col: r.get(c) is None)
        return self

    def limit(self, n):
        self._limit = n
        return self

    def update(self, patch):
        self._patch = patch
        return self

    def execute(self):
        rows = [r for r in self._store.get(self._table, [])
                if all(f(r) for f in self._filters)]
        if self._patch is not None:
            for r in rows:
                r.update(self._patch)
        if self._limit is not None:
            rows = rows[:self._limit]
        return type("R", (), {"data": [dict(r) for r in rows]})()


class _DB:
    def __init__(self, **tables):
        self.store = tables

    def table(self, name):
        return _Q(self.store, name)


def _reg(reg_id, client_id):
    return {"id": reg_id, "firm_id": "F1", "client_id": client_id,
            "gstin": "29AAPFU0939F1ZR", "state_code": "29",
            "registration_type": "regular", "filing_frequency": "monthly",
            "trade_name": None, "effective_from": None, "effective_to": None,
            "deleted_at": None}


# ── The service: the client is part of the match ───────────────────────────

def test_closing_another_clients_registration_is_a_404_and_touches_nothing():
    db = _DB(client_gst_registrations=[_reg("R-B", "C-B")])
    with pytest.raises(HTTPException) as e:
        svc.close(db, "F1", "R-B", client_id="C-A", effective_to="2026-09-30")
    assert e.value.status_code == 404
    assert db.store["client_gst_registrations"][0]["effective_to"] is None


def test_a_registration_is_closed_for_its_own_client():
    db = _DB(client_gst_registrations=[_reg("R-B", "C-B")])
    row = svc.close(db, "F1", "R-B", client_id="C-B", effective_to="2026-09-30")
    assert row["effective_to"] == "2026-09-30"
    assert db.store["client_gst_registrations"][0]["effective_to"] == "2026-09-30"


def test_withdrawing_another_clients_registration_is_a_404_and_touches_nothing():
    db = _DB(client_gst_registrations=[_reg("R-B", "C-B")],
             gstr1_returns=[], gstr3b_returns=[])
    with pytest.raises(HTTPException) as e:
        svc.withdraw(db, "F1", "R-B", client_id="C-A")
    assert e.value.status_code == 404
    assert db.store["client_gst_registrations"][0]["deleted_at"] is None


def test_a_registration_is_withdrawn_for_its_own_client():
    db = _DB(client_gst_registrations=[_reg("R-B", "C-B")],
             gstr1_returns=[], gstr3b_returns=[])
    svc.withdraw(db, "F1", "R-B", client_id="C-B")
    assert db.store["client_gst_registrations"][0]["deleted_at"] is not None


def test_the_client_is_required_not_defaulted():
    """A default would let the next caller forget it, which is how the match
    came to be id-and-firm in the first place."""
    db = _DB(client_gst_registrations=[_reg("R-B", "C-B")])
    with pytest.raises(TypeError):
        svc.close(db, "F1", "R-B", effective_to="2026-09-30")
    with pytest.raises(TypeError):
        svc.withdraw(db, "F1", "R-B")


# ── The router: a service client, and the asserted client passed down ──────

@pytest.fixture
def wired(monkeypatch):
    """The router as it runs against a database, with the two clients told
    apart and the service calls recorded."""
    service_db, calls = object(), []

    def _refuse_request_client():
        raise AssertionError("a write used the per-request client, which "
                             "`authenticated` cannot write through")

    monkeypatch.setattr(router, "_mock_enabled", lambda: False)
    monkeypatch.setattr(sc, "get_service_supabase", lambda: service_db)
    monkeypatch.setattr(sc, "get_supabase", _refuse_request_client)
    monkeypatch.setattr(audit, "log_event", lambda *a, **k: None)

    def record(name):
        def _call(db, *args, **kwargs):
            calls.append((name, db, args, kwargs))
            return {"id": "R1"}
        return _call

    monkeypatch.setattr(svc, "create", record("create"))
    monkeypatch.setattr(svc, "close", record("close"))
    monkeypatch.setattr(svc, "withdraw", record("withdraw"))
    return service_db, calls


def test_add_writes_through_the_service_role(wired):
    service_db, calls = wired
    router.add_registration(
        router.RegistrationIn(client_id="C-A", gstin="29AAPFU0939F1ZR"), CALLER)
    (name, db, args, _kw), = calls
    assert name == "create" and db is service_db
    assert args[:2] == ("F1", "C-A")


def test_close_writes_through_the_service_role_for_the_asserted_client(wired):
    service_db, calls = wired
    router.close_registration(
        "R-B", router.CloseRegistrationIn(client_id="C-A", effective_to="2026-09-30"),
        CALLER)
    (name, db, args, kw), = calls
    assert name == "close" and db is service_db
    assert args == ("F1", "R-B")
    assert kw["client_id"] == "C-A"


def test_withdraw_writes_through_the_service_role_for_the_asserted_client(wired):
    service_db, calls = wired
    router.withdraw_registration("R-B", "C-A", CALLER)
    (name, db, args, kw), = calls
    assert name == "withdraw" and db is service_db
    assert args == ("F1", "R-B")
    assert kw["client_id"] == "C-A"
