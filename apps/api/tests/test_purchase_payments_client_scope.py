"""
Client-assignment scope on the purchase_payments router — the AP mirror of
receipts.py.

list_purchase_payments took the required client_id from the query string and
never checked it. create_purchase_payment takes client_id in the body
(PurchasePaymentIn) — validated it belonged to the vendor's own books but
never checked the CALLER's assignment. get_purchase_payment/
reverse_purchase_payment are row-addressed by payment_id and checked only
firm_id; new _assert_payment_scope resolver closes both.
update_purchase_payment_allocations delegates to services/
purchase_payment_service.py's update_allocations_core, which now checks
can_access_client right where it resolves client_id off the payment row.
"""
import pytest
from fastapi import HTTPException

import routers.purchase_payments as pp
import services.purchase_payment_service as pps

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

    monkeypatch.setattr(pp, "assert_client_access", _assert)
    monkeypatch.setattr(pp, "can_access_client", _can)
    return seen


# ══════════════════════════════════════════════════════════════════════════════
# list_purchase_payments — client_id from the query string
# ══════════════════════════════════════════════════════════════════════════════

def test_listing_another_clients_payments_is_refused(deny):
    with pytest.raises(HTTPException) as e:
        pp.list_purchase_payments(client_id=THEIRS, vendor_id=None, purchase_bill_id=None,
                                   from_date=None, to_date=None, limit=50, offset=0, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_listing_your_own_clients_payments_still_works(deny):
    out = pp.list_purchase_payments(client_id=MINE, vendor_id=None, purchase_bill_id=None,
                                     from_date=None, to_date=None, limit=50, offset=0, current_user=USER)
    assert out["success"] is True
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# create_purchase_payment — client_id in the body
# ══════════════════════════════════════════════════════════════════════════════

def test_creating_a_payment_for_another_clients_is_refused(deny):
    data = pp.PurchasePaymentIn(client_id=THEIRS, vendor_id="V1", payment_date="2026-04-15", amount_paise=1000)
    with pytest.raises(HTTPException) as e:
        pp.create_purchase_payment(data, current_user=USER)
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_creating_a_payment_for_your_own_client_still_works(deny):
    data = pp.PurchasePaymentIn(client_id=MINE, vendor_id="V1", payment_date="2026-04-15", amount_paise=1000)
    out = pp.create_purchase_payment(data, current_user=USER)
    assert out["data"]["client_id"] == MINE
    assert deny == [MINE]


# ══════════════════════════════════════════════════════════════════════════════
# _assert_payment_scope + get_purchase_payment/reverse_purchase_payment
# (live-mode path — mock mode is a permissive no-op with nothing to
# protect, the same shape as income_tax.py's _assert_capital_gains_scope)
# ══════════════════════════════════════════════════════════════════════════════

class _SingleQuery:
    def __init__(self, row):
        self.row = row

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def maybe_single(self):
        return self

    def execute(self):
        class _R:
            pass
        r = _R()
        r.data = self.row
        return r


class _SingleDb:
    def __init__(self, row):
        self.row = row

    def table(self, _name):
        return _SingleQuery(self.row)


def test_payment_scope_refuses_another_clients_record(deny, monkeypatch):
    monkeypatch.setattr(pp, "_USE_MOCK", False)
    monkeypatch.setattr(pp, "_get_db", lambda: _SingleDb({"id": "PMT-1", "client_id": THEIRS}))
    with pytest.raises(HTTPException) as e:
        pp._assert_payment_scope(USER, "PMT-1")
    assert e.value.status_code == 404
    assert deny == [THEIRS]


def test_payment_scope_allows_your_own_record(deny, monkeypatch):
    monkeypatch.setattr(pp, "_USE_MOCK", False)
    row = {"id": "PMT-1", "client_id": MINE}
    monkeypatch.setattr(pp, "_get_db", lambda: _SingleDb(row))
    assert pp._assert_payment_scope(USER, "PMT-1") == row
    assert deny == [MINE]


def test_missing_and_hidden_payments_use_the_identical_message(deny, monkeypatch):
    monkeypatch.setattr(pp, "_USE_MOCK", False)
    monkeypatch.setattr(pp, "_get_db", lambda: _SingleDb(None))
    with pytest.raises(HTTPException) as missing:
        pp._assert_payment_scope(USER, "PMT-NOPE")

    monkeypatch.setattr(pp, "_get_db", lambda: _SingleDb({"id": "PMT-1", "client_id": THEIRS}))
    with pytest.raises(HTTPException) as hidden:
        pp._assert_payment_scope(USER, "PMT-1")

    assert missing.value.status_code == hidden.value.status_code == 404
    assert missing.value.detail == hidden.value.detail == "Payment not found"


def test_getting_another_clients_payment_is_refused(deny, monkeypatch):
    monkeypatch.setattr(pp, "_USE_MOCK", False)
    monkeypatch.setattr(pp, "_get_db", lambda: _SingleDb({"id": "PMT-1", "client_id": THEIRS}))
    with pytest.raises(HTTPException) as e:
        pp.get_purchase_payment("PMT-1", current_user=USER)
    assert e.value.status_code == 404
    assert e.value.detail == "Payment not found"


def test_getting_your_own_payment_still_works(deny, monkeypatch):
    monkeypatch.setattr(pp, "_USE_MOCK", False)
    row = {"id": "PMT-1", "client_id": MINE}
    monkeypatch.setattr(pp, "_get_db", lambda: _SingleDb(row))
    out = pp.get_purchase_payment("PMT-1", current_user=USER)
    assert out["data"]["id"] == "PMT-1"


def test_reversing_another_clients_payment_is_refused(deny, monkeypatch):
    monkeypatch.setattr(pp, "_USE_MOCK", False)
    monkeypatch.setattr(pp, "_assert_payment_scope", lambda user, pid: (_ for _ in ()).throw(
        HTTPException(status_code=404, detail="Payment not found")))
    called = []
    monkeypatch.setattr(pp.reversal_service, "reverse_payment", lambda *a, **kw: called.append((a, kw)))
    with pytest.raises(HTTPException):
        pp.reverse_purchase_payment("PMT-THEIRS", pp.JournalReversalIn(reversal_date="2026-04-15"), current_user=USER)
    assert not called   # refused before the reversal service ever ran


# ══════════════════════════════════════════════════════════════════════════════
# purchase_payment_service.update_allocations_core — the sole caller-facing
# delegation, guarded at the call site rather than in the router.
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

    def delete(self, *_a, **_k):
        return self

    def insert(self, *_a, **_k):
        return self

    def update(self, *_a, **_k):
        return self

    def execute(self):
        class _R:
            pass
        r = _R()
        r.data = self.rows
        return r


class _FakeDb:
    def __init__(self, payment_rows, alloc_rows=None):
        self.payment_rows = payment_rows
        self.alloc_rows = alloc_rows or []

    def table(self, name):
        if name == "purchase_payments":
            return _FakeQuery(self.payment_rows)
        return _FakeQuery(self.alloc_rows)


def test_update_allocations_core_refuses_another_clients_payment(monkeypatch):
    seen = []
    monkeypatch.setattr(pps, "can_access_client", lambda user, cid: seen.append(cid) or cid != THEIRS)
    db = _FakeDb([{"amount_paise": 1000, "client_id": THEIRS}])
    with pytest.raises(HTTPException) as e:
        pps.update_allocations_core(FIRM, "PMT-1", [], USER, db)
    assert e.value.status_code == 404
    assert e.value.detail == "Payment PMT-1 not found"
    assert seen == [THEIRS]


def test_update_allocations_core_allows_your_own_payment(monkeypatch):
    seen = []
    monkeypatch.setattr(pps, "can_access_client", lambda user, cid: seen.append(cid) or cid != THEIRS)
    db = _FakeDb([{"amount_paise": 1000, "client_id": MINE}])
    # No allocations requested — should proceed past the scope check without
    # erroring on the (unrelated) allocation logic below it.
    result = pps.update_allocations_core(FIRM, "PMT-1", [], USER, db)
    assert seen == [MINE]
    assert result["payment_id"] == "PMT-1"
