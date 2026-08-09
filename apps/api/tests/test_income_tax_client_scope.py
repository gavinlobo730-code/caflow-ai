"""
Client-assignment scope on the income_tax (ITR computation) router.

/compute, /hra/compute, /capital-gains/cii-table, /capital-gains/compute and
/advance-tax/compute are stateless calculators — none of their request
models carry a client_id, so there is nothing to check (EXEMPT in the
ratchet). create_capital_gains and save_advance_tax already called
assert_client_access before this phase (tasks #238/#230).

This phase closes the rest: list_capital_gains and list_advance_tax took
client_id from the query string and only ever filtered it into the
firm-scoped WHERE clause, never checking it against the caller's
assignment; delete_capital_gains is row-addressed by record_id and checked
only firm_id, the same "guarded on the write-with-a-body, not the
row-addressed sibling" shape found across this sweep.
"""
import pytest
from fastapi import HTTPException

import routers.income_tax as it

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else. Patches assert_client_access
    and can_access_client on the router module, mirroring the other
    *_client_scope.py test files in this sweep."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(it, "assert_client_access", _assert)
    monkeypatch.setattr(it, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# list_capital_gains / list_advance_tax — client_id from the query string
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_clients_capital_gains_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        it.list_capital_gains(client_id=THEIRS, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_listing_your_own_clients_capital_gains_still_works(deny):
    out = it.list_capital_gains(client_id=MINE, current_user=USER)
    assert out["data"] == []          # mock mode: _db() is None
    assert deny == [MINE]


def test_listing_another_clients_advance_tax_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        it.list_advance_tax(client_id=THEIRS, fy="2025-26", current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_listing_your_own_clients_advance_tax_still_works(deny):
    out = it.list_advance_tax(client_id=MINE, fy="2025-26", current_user=USER)
    assert out["data"] == []
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# _assert_capital_gains_scope + delete_capital_gains — row-addressed
# ══════════════════════════════════════════════════════════════════════════════

class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def delete(self, *_a, **_k):
        return self

    def execute(self):
        class _R:
            pass
        r = _R()
        r.data = self.rows
        return r


class _FakeDb:
    def __init__(self, rows):
        self.rows = rows

    def table(self, _name):
        return _FakeQuery(self.rows)


def test_capital_gains_scope_refuses_another_clients_record(deny):
    db = _FakeDb([{"id": "CG-THEIRS", "client_id": THEIRS}])
    with pytest.raises(HTTPException) as e:
        it._assert_capital_gains_scope(USER, "CG-THEIRS", db)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_capital_gains_scope_allows_your_own_record(deny):
    db = _FakeDb([{"id": "CG-MINE", "client_id": MINE}])
    it._assert_capital_gains_scope(USER, "CG-MINE", db)   # does not raise
    assert deny == [MINE]


def test_capital_gains_scope_is_a_noop_in_mock_mode(deny):
    """Mock mode (db is None) has no persistent store to protect against —
    matching every other handler in this module."""
    it._assert_capital_gains_scope(USER, "whatever-id", None)
    assert deny == []


def test_missing_and_hidden_capital_gains_use_the_identical_message(deny):
    db_missing = _FakeDb([])
    db_hidden = _FakeDb([{"id": "CG-THEIRS", "client_id": THEIRS}])
    with pytest.raises(HTTPException) as missing:
        it._assert_capital_gains_scope(USER, "CG-NOPE", db_missing)
    with pytest.raises(HTTPException) as hidden:
        it._assert_capital_gains_scope(USER, "CG-THEIRS", db_hidden)
    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Capital gains record not found"


def test_deleting_another_clients_capital_gains_record_is_refused(deny, monkeypatch):
    db = _FakeDb([{"id": "CG-THEIRS", "client_id": THEIRS}])
    monkeypatch.setattr(it, "_db", lambda: db)
    with pytest.raises(HTTPException):
        it.delete_capital_gains("CG-THEIRS", current_user=USER)


def test_deleting_your_own_capital_gains_record_still_works(deny, monkeypatch):
    db = _FakeDb([{"id": "CG-MINE", "client_id": MINE}])
    monkeypatch.setattr(it, "_db", lambda: db)
    out = it.delete_capital_gains("CG-MINE", current_user=USER)
    assert out["data"]["id"] == "CG-MINE"


def test_deleting_in_mock_mode_still_works(deny, monkeypatch):
    monkeypatch.setattr(it, "_db", lambda: None)
    out = it.delete_capital_gains("whatever-id", current_user=USER)
    assert out["data"]["id"] == "whatever-id"
    assert deny == []
