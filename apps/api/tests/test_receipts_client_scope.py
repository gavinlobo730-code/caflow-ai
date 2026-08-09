"""
Client-assignment scope on the receipts router — customer receipts, the AR
settlement engine's thin wrapper.

list_receipts took the required client_id from the query string and never
checked it. create_receipt takes client_id in the body (ReceiptIn) and
delegates to services.receipt_service.create_receipt_core, which only ever
scopes by firm+client for data isolation — never checks the CALLER's
assignment — so the guard is added at the router call site.
get_receipt/update_allocations/reverse_receipt are all row-addressed by
receipt_id and previously checked only firm_id; new _assert_receipt_scope
resolver closes all three.
"""
import pytest
from fastapi import HTTPException

import routers.receipts as rc

FIRM = "firm-1"
MINE, THEIRS = "client-mine", "client-theirs"
USER = {"id": "u1", "firm_id": FIRM, "auth_user_id": "u1", "role": "Manager"}


@pytest.fixture
def deny(monkeypatch):
    """Refuse THEIRS, allow everything else. Patches assert_client_access/
    can_access_client on the router module, mirroring the other
    *_client_scope.py test files in this sweep."""
    seen = []

    def _assert(user, client_id):
        seen.append(client_id)
        if client_id == THEIRS:
            raise HTTPException(status_code=404, detail="Not found")

    def _can(user, client_id):
        seen.append(client_id)
        return client_id != THEIRS

    monkeypatch.setattr(rc, "assert_client_access", _assert)
    monkeypatch.setattr(rc, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# list_receipts — client_id from the query string
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_clients_receipts_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        rc.list_receipts(client_id=THEIRS, customer_id=None, from_date=None, to_date=None,
                          limit=50, offset=0, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_listing_your_own_clients_receipts_still_works(deny):
    out = rc.list_receipts(client_id=MINE, customer_id=None, from_date=None, to_date=None,
                            limit=50, offset=0, current_user=USER)
    assert out["success"] is True
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# create_receipt — client_id in the body
# ══════════════════════════════════════════════════════════════════════════════

def test_creating_a_receipt_for_another_clients_is_refused(deny, monkeypatch):
    monkeypatch.setattr(rc.receipt_service, "create_receipt_core", lambda **kw: {"id": "R1"})
    data = rc.ReceiptIn(client_id=THEIRS, customer_id="CUST-1", receipt_date="2026-04-15", amount_paise=1000)
    with pytest.raises(HTTPException) as e:
        rc.create_receipt(data, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_creating_a_receipt_for_your_own_client_still_works(deny, monkeypatch):
    monkeypatch.setattr(rc.receipt_service, "create_receipt_core", lambda **kw: {"id": "R1"})
    data = rc.ReceiptIn(client_id=MINE, customer_id="CUST-1", receipt_date="2026-04-15", amount_paise=1000)
    out = rc.create_receipt(data, current_user=USER)
    assert out["data"]["id"] == "R1"
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# _assert_receipt_scope + get_receipt/update_allocations/reverse_receipt
# ══════════════════════════════════════════════════════════════════════════════

class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
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


def test_receipt_scope_refuses_another_clients_record(deny, monkeypatch):
    monkeypatch.setattr(rc, "_USE_MOCK", False)
    db = _FakeDb([{"id": "REC-THEIRS", "client_id": THEIRS}])
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    with pytest.raises(HTTPException) as e:
        rc._assert_receipt_scope(USER, "REC-THEIRS")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_receipt_scope_allows_your_own_record(deny, monkeypatch):
    monkeypatch.setattr(rc, "_USE_MOCK", False)
    row = {"id": "REC-MINE", "client_id": MINE}
    db = _FakeDb([row])
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db)
    assert rc._assert_receipt_scope(USER, "REC-MINE") == row
    assert deny == [MINE]


def test_missing_and_hidden_receipts_use_the_identical_message(deny, monkeypatch):
    monkeypatch.setattr(rc, "_USE_MOCK", False)
    db_missing = _FakeDb([])
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db_missing)
    with pytest.raises(HTTPException) as missing:
        rc._assert_receipt_scope(USER, "REC-1")

    db_hidden = _FakeDb([{"id": "REC-1", "client_id": THEIRS}])
    monkeypatch.setattr("core.supabase_client.get_supabase", lambda: db_hidden)
    with pytest.raises(HTTPException) as hidden:
        rc._assert_receipt_scope(USER, "REC-1")

    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Receipt REC-1 not found"


def test_getting_another_clients_receipt_is_refused(deny, monkeypatch):
    monkeypatch.setattr(rc, "_assert_receipt_scope", lambda user, rid: (_ for _ in ()).throw(
        HTTPException(status_code=404, detail=f"Receipt {rid} not found")))
    with pytest.raises(HTTPException) as e:
        rc.get_receipt("REC-THEIRS", current_user=USER)
    assert e.value.status_code == 404


def test_getting_your_own_receipt_still_works(deny, monkeypatch):
    row = {"id": "REC-MINE", "client_id": MINE, "amount_paise": 1000}
    monkeypatch.setattr(rc, "_assert_receipt_scope", lambda user, rid: row)
    monkeypatch.setattr(rc, "_USE_MOCK", True)
    out = rc.get_receipt("REC-MINE", current_user=USER)
    assert out["data"]["id"] == "REC-MINE"


def test_reversing_another_clients_receipt_is_refused(deny, monkeypatch):
    monkeypatch.setattr(rc, "_USE_MOCK", False)
    monkeypatch.setattr(rc, "_assert_receipt_scope", lambda user, rid: (_ for _ in ()).throw(
        HTTPException(status_code=404, detail=f"Receipt {rid} not found")))
    called = []
    monkeypatch.setattr(rc.reversal_service, "reverse_receipt", lambda *a, **kw: called.append((a, kw)))
    with pytest.raises(HTTPException):
        rc.reverse_receipt("REC-THEIRS", rc.JournalReversalIn(reversal_date="2026-04-15"), current_user=USER)
    assert not called   # refused before the reversal service ever ran
