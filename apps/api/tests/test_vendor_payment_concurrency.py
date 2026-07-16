"""
Vendor Payment concurrency — atomicity tests (H4).

create_purchase_payment() previously read a purchase bill's outstanding
balance, checked the new payment against it, and only reconciled paid_paise
from the ledger AFTER inserting the payment row. Two concurrent requests for
the same bill could both read the same stale paid_paise, both pass the
outstanding check, and both post — overpaying the vendor.

The fix reserves the payment amount atomically (compare-and-swap on
paid_paise) BEFORE any journal or payment row is created, and rolls the
reservation back if the journal/payment insert subsequently fails.
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

    def like(self, k, pattern):
        # only used by _next_payment_seq; no real matching needed for these tests
        return self

    def limit(self, _n):
        return self

    def single(self):
        self.single_ = True
        return self

    def _match(self):
        rows = self.s.setdefault(self.t, [])
        return [r for r in rows if all(r.get(k) == v for k, v in self.f)]

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


def test_single_payment_updates_bill_and_posts_journal(monkeypatch):
    db = FakeDB()
    _seed_bill(db)
    result = _create(monkeypatch, db, _payment(amount_paise=30_000_00))
    assert result["success"] is True
    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 30_000_00
    assert bill["status"] == "partially_paid"


def test_partial_payment_leaves_bill_partially_paid(monkeypatch):
    db = FakeDB()
    _seed_bill(db)
    _create(monkeypatch, db, _payment(amount_paise=40_000_00))
    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 40_000_00
    assert bill["status"] == "partially_paid"


def test_exact_settlement_marks_bill_paid(monkeypatch):
    db = FakeDB()
    _seed_bill(db)
    _create(monkeypatch, db, _payment(amount_paise=100_000_00))
    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 100_000_00
    assert bill["status"] == "paid"


def test_overpayment_is_rejected(monkeypatch):
    db = FakeDB()
    _seed_bill(db)
    with pytest.raises(HTTPException) as exc:
        _create(monkeypatch, db, _payment(amount_paise=150_000_00))
    assert exc.value.status_code == 422
    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 0  # rejected before any claim was made


def test_second_payment_cannot_push_bill_past_outstanding(monkeypatch):
    """The classic sequential-but-uncoordinated case: two payments, each
    individually under the full net_payable, whose SUM exceeds it."""
    db = FakeDB()
    _seed_bill(db, net_payable_paise=100_000_00)
    _create(monkeypatch, db, _payment(amount_paise=70_000_00))
    with pytest.raises(HTTPException) as exc:
        _create(monkeypatch, db, _payment(amount_paise=70_000_00))
    assert exc.value.status_code == 422
    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 70_000_00  # only the first payment claimed


def test_concurrent_payments_race_the_same_bill_only_one_wins(monkeypatch):
    """Simulates the exact H4 race with real threads: two requests both read
    paid_paise=0 (via a barrier that holds both at that read) before either's
    CAS-update commits. The CAS in _claim_bill_outstanding must serialize them
    — the loser must lose its first CAS attempt, re-read the now-current
    paid_paise, and be rejected — instead of both succeeding and overpaying."""
    db = FakeDB()
    _seed_bill(db, net_payable_paise=100_000_00)
    monkeypatch.setattr(pp_router, "_get_db", lambda: db)
    from services.phase2_journal_service import phase2_journal_service
    monkeypatch.setattr(phase2_journal_service, "journal_for_purchase_payment", lambda *a, **k: "je-1")

    barrier = threading.Barrier(2, timeout=5)
    hit_count = {"n": 0}
    lock = threading.Lock()
    real_execute = _Q.execute

    def racy_execute(self):
        if self.t == "purchase_bills" and self.op == "select" and self.cols == "paid_paise":
            with lock:
                hit_count["n"] += 1
                use_barrier = hit_count["n"] <= 2
            if use_barrier:
                try:
                    barrier.wait()
                except threading.BrokenBarrierError:
                    pass
        return real_execute(self)

    monkeypatch.setattr(_Q, "execute", racy_execute)
    results, errors = [], []
    results_lock = threading.Lock()

    def worker():
        try:
            r = pp_router.create_purchase_payment(_payment(amount_paise=70_000_00), {"firm_id": FIRM, "id": "u1"})
            with results_lock:
                results.append(r)
        except HTTPException as e:
            with results_lock:
                errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(results) == 1
    assert len(errors) == 1
    assert errors[0].status_code == 422
    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 70_000_00  # exactly one payment's worth claimed


def test_update_bill_payment_status_never_regresses_a_concurrent_claim(monkeypatch):
    """task #102: _update_bill_payment_status used to blindly overwrite
    paid_paise with sum(purchase_payments.amount_paise) — a DIFFERENT source
    than the column it was overwriting. If a concurrent payment's
    _claim_bill_outstanding CAS already bumped bill.paid_paise but that
    payment's OWN purchase_payments row hasn't been inserted yet, the recompute
    sees an incomplete sum and used to clobber the correct, already-claimed
    total down to a stale, lower one — silently erasing the concurrent
    payment's claim. It must never write a value lower than what's already
    stored."""
    db = FakeDB()
    _seed_bill(db, paid_paise=100_000_00, net_payable_paise=200_000_00, status="partially_paid")
    # Only ONE payment row is visible — simulating a second, concurrent
    # payment whose CAS claim already landed on the bill but whose OWN
    # purchase_payments row insert hasn't committed yet.
    db.store.setdefault("purchase_payments", []).append(
        {"id": "pp-1", "firm_id": FIRM, "purchase_bill_id": "bill-1", "amount_paise": 70_000_00})

    pp_router._update_bill_payment_status(db, FIRM, CLIENT, "bill-1")

    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 100_000_00     # untouched — never regressed
    assert bill["status"] == "partially_paid"


def test_update_bill_payment_status_reconciles_upward_when_stale(monkeypatch):
    """The self-healing direction must still work: when the payments ledger
    legitimately sums higher than the bill's stored paid_paise (drift), the
    bill is brought up to match."""
    db = FakeDB()
    _seed_bill(db, paid_paise=30_000_00, net_payable_paise=200_000_00, status="partially_paid")
    db.store.setdefault("purchase_payments", []).append(
        {"id": "pp-1", "firm_id": FIRM, "purchase_bill_id": "bill-1", "amount_paise": 30_000_00})
    db.store["purchase_payments"].append(
        {"id": "pp-2", "firm_id": FIRM, "purchase_bill_id": "bill-1", "amount_paise": 70_000_00})

    pp_router._update_bill_payment_status(db, FIRM, CLIENT, "bill-1")

    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 100_000_00
    assert bill["status"] == "partially_paid"


def test_claim_rollback_on_downstream_failure_restores_outstanding(monkeypatch):
    """If the journal/payment insert fails AFTER the bill claim succeeded, the
    claim must be rolled back so the bill's outstanding is not wrongly reduced."""
    db = FakeDB()
    _seed_bill(db)
    monkeypatch.setattr(pp_router, "_get_db", lambda: db)
    from services.phase2_journal_service import phase2_journal_service
    monkeypatch.setattr(phase2_journal_service, "journal_for_purchase_payment", lambda *a, **k: "je-1")

    orig_insert = _Q.insert

    def failing_insert(self, p):
        if self.t == "purchase_payments":
            raise RuntimeError("simulated insert failure")
        return orig_insert(self, p)

    monkeypatch.setattr(_Q, "insert", failing_insert)

    # create_purchase_payment's own top-level try/except converts an unhandled
    # failure into an error response rather than propagating — the claim's
    # rollback must still have run before that happens.
    result = pp_router.create_purchase_payment(_payment(amount_paise=30_000_00), {"firm_id": FIRM, "id": "u1"})
    assert result["success"] is False

    bill = db.store["purchase_bills"][0]
    assert bill["paid_paise"] == 0
    assert bill["status"] == "received"

    monkeypatch.setattr(_Q, "insert", orig_insert)

    # A full-amount payment should now succeed cleanly — proving the claim was
    # actually released, not left stuck at a phantom partial reservation.
    result = _create(monkeypatch, db, _payment(amount_paise=100_000_00))
    assert result["success"] is True
    assert db.store["purchase_bills"][0]["status"] == "paid"
