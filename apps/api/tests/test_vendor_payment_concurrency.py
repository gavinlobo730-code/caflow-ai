"""
Vendor payment: what is left here of the H4 atomicity tests.

create_purchase_payment() once read a purchase bill's outstanding balance, checked the new payment against it, and only reconciled
paid_paise from the ledger AFTER inserting the payment row, so two concurrent requests could both pass the check and overpay the
vendor. H4 answered that with a compare-and-set reservation on the bill BEFORE the journal and the payment, given back when either
failed; six tests here drove it (with threads, on this file's own fake).

Since POST-A-575 (migration 784) the entry, the payment and the bill's paid amount are ONE database transaction that locks the bill
row, so there is no reservation to make or give back. Those six tests went with the code they drove. What they guarded is held:
  * against PostgreSQL, with two real sessions racing for one bill, in
    tests/test_784_a_supplier_payment_is_recorded_in_one_transaction_pg.py;
  * on the in-memory double of the function, in tests/test_a_supplier_payment_is_one_database_transaction.py (a part payment and the
    rest, more than is left, a payment overtaken at its bill, a refusal that leaves nothing).

What stays: the refusal of an overpayment from the route's own read. (`_update_bill_payment_status`, which recomputed a bill from
its payments after the insert, had no caller left once the payment and the bill were written together, and went with its tests;
the security-closure 5.1c test file held only two of them and went too.)
"""
import sys
import os
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from fastapi import HTTPException

import routers.purchase_payments as pp_router
from models.invoices import PurchasePaymentIn

FIRM, CLIENT, VENDOR = "firm-1", "client-1", "vendor-1"


# ── Fake Supabase (same shape/semantics as test_fixed_asset_disposal.py's FakeDB,
#    with real filtering so a CAS's .eq("paid_paise", <value>) guard actually works) ──

class _Resp:
    def __init__(self, data):
        self.data = data


class _Q:
    def __init__(self, store, table):
        self.s, self.t = store, table
        self.op = "select"
        self.payload = None
        self.f = []
        self.single_ = False
        self.count_ = None
        self.cols = ""

    def insert(self, p):
        self.op, self.payload = "insert", p
        return self

    def update(self, p):
        self.op, self.payload = "update", p
        return self

    def select(self, *a, count=None, **k):
        self.op = "select"
        self.cols = " ".join(str(x) for x in a)
        self.count_ = count
        return self

    def eq(self, k, v):
        self.f.append((k, v))
        return self

    def neq(self, k, v):
        # A real filter, not a no-op: create_purchase_payment reads the vendor's
        # OPEN payable before deciding what part of a payment is an advance
        # (§194 charges at credit or payment, whichever is earlier), and it
        # excludes cancelled bills. A double that ignored the exclusion would
        # let a cancelled bill make an advance look settled.
        self.f.append(("!=" + k, v))
        return self

    def like(self, k, pattern):
        # only used by _next_payment_seq; no real matching needed for these tests
        return self

    # _next_payment_seq now reads the highest number back rather than counting
    # rows (SALES-04), so it orders and bounds the read.
    def order(self, *a, **k):
        return self

    def limit(self, _n):
        return self

    def single(self):
        self.single_ = True
        return self

    def _match(self):
        rows = self.s.setdefault(self.t, [])
        def keep(r):
            for k, v in self.f:
                if k.startswith("!="):
                    if r.get(k[2:]) == v:
                        return False
                elif r.get(k) != v:
                    return False
            return True
        return [r for r in rows if keep(r)]

    # A single lock stands in for Postgres's per-row write lock: it makes the
    # match-then-mutate step of an "update" atomic, so a .eq("paid_paise", X)
    # guard behaves the same under real concurrent threads as it does against
    # a real UPDATE ... WHERE statement (the whole point of this fake, for the
    # threaded race test below — every other test here is single-threaded and
    # unaffected by it).
    _write_lock = threading.Lock()

    def execute(self):
        if self.op == "insert":
            rows = self.s.setdefault(self.t, [])
            items = self.payload if isinstance(self.payload, list) else [self.payload]
            ins = []
            for p in items:
                rec = dict(p)
                rec.setdefault("id", f"{self.t}-{len(rows) + 1}")
                rows.append(rec)
                ins.append(rec)
            return _Resp(ins)
        if self.op == "update":
            with _Q._write_lock:
                m = self._match()
                for r in m:
                    r.update(self.payload)
            return _Resp(m)
        m = self._match()
        if self.count_ == "exact":
            r = _Resp(m)
            r.count = len(m)
            return r
        if self.single_:
            return _Resp(m[0] if m else None)
        return _Resp(m)


class FakeDB:
    def __init__(self):
        self.store = {}

    def table(self, name):
        return _Q(self.store, name)


def _seed_bill(db, **overrides):
    # task #227: create_purchase_payment now rejects a vendor_id that isn't
    # found in THIS firm+client's books (previously failed open on no
    # match) — every test here pays VENDOR against CLIENT, so it must exist.
    db.store.setdefault("vendors", []).append(
        {"id": VENDOR, "firm_id": FIRM, "client_id": CLIENT, "is_active": True}
    )
    bill = {
        "id": "bill-1", "firm_id": FIRM, "client_id": CLIENT, "vendor_id": VENDOR,
        "status": "received", "net_payable_paise": 100_000_00, "paid_paise": 0,
    }
    bill.update(overrides)
    db.store.setdefault("purchase_bills", []).append(bill)
    return bill


@pytest.fixture(autouse=True)
def _patch(monkeypatch):
    monkeypatch.setattr(pp_router, "_USE_MOCK", False)
    monkeypatch.setattr(pp_router, "log_event", lambda *a, **k: None)
    monkeypatch.setattr(pp_router.period_validation_service, "validate_posting_date", lambda *a, **k: None)
    monkeypatch.setattr(pp_router.timeline_service, "log_timeline_event", lambda *a, **k: None)
    yield


def _payment(**overrides):
    payload = {
        "client_id": CLIENT, "vendor_id": VENDOR, "payment_date": "2026-06-15",
        "amount_paise": 30_000_00, "purchase_bill_id": "bill-1", "currency": "INR",
    }
    payload.update(overrides)
    return PurchasePaymentIn(**payload)


def _create(monkeypatch, db, data, journal_id="je-1"):
    monkeypatch.setattr(pp_router, "_get_db", lambda: db)
    from services.phase2_journal_service import phase2_journal_service
    monkeypatch.setattr(phase2_journal_service, "journal_for_purchase_payment", lambda *a, **k: journal_id)
    return pp_router.create_purchase_payment(data, {"firm_id": FIRM, "id": "u1"})


def test_overpayment_is_rejected(monkeypatch):
    db = FakeDB()
    _seed_bill(db)
    with pytest.raises(HTTPException) as exc:
        _create(monkeypatch, db, _payment(amount_paise=150_000_00))
    assert exc.value.status_code == 422
    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 0  # rejected before any claim was made
