"""
R2.9 — a receipt_no/payment_no unique-constraint collision (migration 159)
must reverse the already-posted journal rather than leave a phantom GL entry,
since both receipts and purchase payments post their journal BEFORE the
number-bearing insert (F7/R1.6's journal-first ordering). Before this
milestone the insert could never fail this way (no constraint existed);
adding the constraint without this compensation would have silently
reintroduced the exact "phantom journal, no sub-ledger row" bug class F7
fixed for the allocation step — just one step earlier, at the insert itself.

Runs everywhere (mock-mode style, no real database — the real-Postgres
proof of the constraint itself lives in test_r2_9_document_numbering_pg.py).
A raising fake DB/table stands in for the unique-constraint violation
Postgres would raise.
"""
from __future__ import annotations

import os

os.environ.pop("SUPABASE_URL", None)

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

FIRM = "firm-1"
CLIENT = "client-1"
CUSTOMER = "cust-1"

_DUPLICATE_KEY_ERROR = RuntimeError(
    'duplicate key value violates unique constraint "receipts_firm_client_receipt_no_key"'
)


class _EmptyTable:
    """A supabase-py query-builder stub whose every read returns no rows."""

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        return SimpleNamespace(data=[], count=0)


class _RaisingReceiptsTable(_EmptyTable):
    def __init__(self, error):
        self._error = error

    def insert(self, *_a, **_k):
        return self

    def execute(self):
        raise self._error


def _fake_db(insert_error):
    receipts = _RaisingReceiptsTable(insert_error)

    class _DB:
        def table(self, name):
            if name == "receipts":
                return receipts
            return _EmptyTable()

    return _DB()


# ─── services/receipt_service.py: create_receipt_core (INR path) ───────────

def test_receipt_collision_reverses_journal_and_raises_409(monkeypatch):
    import services.receipt_service as mod
    import services.phase2_journal_service as journal_mod

    compensated = {}

    def fake_compensate(db, firm_id, client_id, receipt_id, journal_id, actor, attempted_ids):
        compensated["called"] = True
        compensated["journal_id"] = journal_id
        compensated["firm_id"] = firm_id

    monkeypatch.setattr(mod, "_compensate_failed_settlement", fake_compensate)
    monkeypatch.setattr(
        journal_mod.phase2_journal_service, "journal_for_receipt",
        lambda **kwargs: "journal-abc-123",
    )
    monkeypatch.setattr(mod, "_next_receipt_seq", lambda db, firm_id, client_id, fy: 1)

    db = _fake_db(_DUPLICATE_KEY_ERROR)

    with pytest.raises(HTTPException) as exc_info:
        mod.create_receipt_core(
            firm_id=FIRM,
            data={
                "client_id": CLIENT, "customer_id": CUSTOMER,
                "amount_paise": 10000, "receipt_date": "2026-04-05",
                "allocations": [],
            },
            actor={"id": "u1", "auth_user_id": "u1", "email": "a@b.com"},
            db=db,
        )

    assert exc_info.value.status_code == 409
    assert "collision" in exc_info.value.detail.lower()
    assert compensated.get("called") is True
    assert compensated.get("journal_id") == "journal-abc-123"
    assert compensated.get("firm_id") == FIRM


def test_receipt_non_collision_error_still_compensates_but_reraises_original(monkeypatch):
    """A failure unrelated to numbering (network blip, etc.) must still reverse
    the journal — but must NOT be reclassified as a 409 numbering collision."""
    import services.receipt_service as mod
    import services.phase2_journal_service as journal_mod

    compensated = {"called": False}

    def fake_compensate(db, firm_id, client_id, receipt_id, journal_id, actor, attempted_ids):
        compensated["called"] = True

    monkeypatch.setattr(mod, "_compensate_failed_settlement", fake_compensate)
    monkeypatch.setattr(
        journal_mod.phase2_journal_service, "journal_for_receipt",
        lambda **kwargs: "journal-abc-123",
    )
    monkeypatch.setattr(mod, "_next_receipt_seq", lambda db, firm_id, client_id, fy: 1)

    db = _fake_db(ConnectionError("connection reset by peer"))

    with pytest.raises(ConnectionError):
        mod.create_receipt_core(
            firm_id=FIRM,
            data={
                "client_id": CLIENT, "customer_id": CUSTOMER,
                "amount_paise": 10000, "receipt_date": "2026-04-05",
                "allocations": [],
            },
            actor={"id": "u1", "auth_user_id": "u1", "email": "a@b.com"},
            db=db,
        )

    assert compensated["called"] is True


# ─── routers/purchase_payments.py: _insert_payment_or_compensate ───────────
# Shared by both the INR path and _create_foreign_payment — one test covers
# the compensation behaviour common to both call sites.

class _RaisingTable:
    """Each db.table() call returns a FRESH instance (see _DB below), so mode
    tracking per-instance is safe: the insert chain raises; the ownership-check
    SELECT chain (a separate .table() call, separate instance) returns no rows,
    i.e. "nobody else owns this journal" — preserving these tests' original
    reverses-as-before behaviour now that the collision path also does an
    ownership check before reversing (see the *_owned_by_another tests below)."""

    def __init__(self, error):
        self._error = error
        self._mode = None

    def insert(self, *_a, **_k):
        self._mode = "insert"
        return self

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        if self._mode == "insert":
            raise self._error
        return SimpleNamespace(data=[])


def test_payment_collision_reverses_journal_and_raises_409(monkeypatch):
    import routers.purchase_payments as mod
    import services.phase2_journal_service as journal_mod

    reversed_calls = []
    monkeypatch.setattr(
        journal_mod.phase2_journal_service, "reverse_entry",
        lambda db, firm_id, entry_id, *a, **k: reversed_calls.append((firm_id, entry_id)),
    )

    class _DB:
        def table(self, _name):
            return _RaisingTable(RuntimeError(
                'duplicate key value violates unique constraint "purchase_payments_firm_payment_no_key"'
            ))

    with pytest.raises(HTTPException) as exc_info:
        mod._insert_payment_or_compensate(
            _DB(), "firm-1", {"payment_no": "VPMT-2526-0001"}, "journal-xyz", "user-1",
        )

    assert exc_info.value.status_code == 409
    assert "collision" in exc_info.value.detail.lower()
    assert reversed_calls == [("firm-1", "journal-xyz")]


def test_payment_non_collision_error_still_reverses_but_reraises_original(monkeypatch):
    import routers.purchase_payments as mod
    import services.phase2_journal_service as journal_mod

    reversed_calls = []
    monkeypatch.setattr(
        journal_mod.phase2_journal_service, "reverse_entry",
        lambda db, firm_id, entry_id, *a, **k: reversed_calls.append((firm_id, entry_id)),
    )

    class _DB:
        def table(self, _name):
            return _RaisingTable(ConnectionError("connection reset by peer"))

    with pytest.raises(ConnectionError):
        mod._insert_payment_or_compensate(
            _DB(), "firm-1", {"payment_no": "VPMT-2526-0001"}, "journal-xyz", "user-1",
        )

    assert reversed_calls == [("firm-1", "journal-xyz")]


class _ReceiptsTableForCompensation:
    """Emulates the `receipts` table for _compensate_failed_settlement's TWO
    calls: the ownership-check SELECT (.select().eq().neq().limit().execute())
    and the compensating DELETE (.delete().eq().execute()). Tracks mode by the
    last verb invoked, same technique used elsewhere in this test file."""

    def __init__(self, existing_owner_id):
        self._existing_owner_id = existing_owner_id
        self._mode = None
        self.deleted_ids = []

    def select(self, *_a, **_k):
        self._mode = "select"
        return self

    def delete(self, *_a, **_k):
        self._mode = "delete"
        return self

    def eq(self, col, val):
        if self._mode == "delete" and col == "id":
            self.deleted_ids.append(val)
        return self

    def neq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        if self._mode == "select":
            data = [{"id": self._existing_owner_id}] if self._existing_owner_id else []
            return SimpleNamespace(data=data)
        return SimpleNamespace(data=[{"id": self.deleted_ids[-1] if self.deleted_ids else None}])


def test_compensate_failed_settlement_skips_reversal_when_journal_owned_by_another_receipt(monkeypatch):
    """The CONFIRMED critical finding: _create_journal's idempotency fast-path
    can hand a losing request the WINNING request's already-committed journal.
    Reversing it would corrupt the winner's books — must be skipped."""
    import services.receipt_service as mod
    import services.phase2_journal_service as journal_mod

    reversed_calls = []
    monkeypatch.setattr(
        journal_mod.phase2_journal_service, "reverse_entry",
        lambda *a, **k: reversed_calls.append(a),
    )

    table = _ReceiptsTableForCompensation(existing_owner_id="other-receipt-id")

    class _DB:
        def table(self, name):
            assert name == "receipts"
            return table

    mod._compensate_failed_settlement(
        _DB(), FIRM, CLIENT, "failed-receipt-id", "journal-shared-123",
        {"id": "u1"}, [],
    )

    assert reversed_calls == [], "must NOT reverse a journal another receipt already owns"
    assert table.deleted_ids == ["failed-receipt-id"], "still cleans up this attempt's own row"


def test_compensate_failed_settlement_reverses_when_journal_unclaimed(monkeypatch):
    """The original F7 behaviour must still work: when nobody else claims the
    journal, it really was created for (and only for) this failed attempt, so
    reversal must proceed exactly as before."""
    import services.receipt_service as mod
    import services.phase2_journal_service as journal_mod

    reversed_calls = []
    monkeypatch.setattr(
        journal_mod.phase2_journal_service, "reverse_entry",
        lambda db, firm_id, journal_id, *a, **k: reversed_calls.append(journal_id),
    )

    table = _ReceiptsTableForCompensation(existing_owner_id=None)

    class _DB:
        def table(self, name):
            return table

    mod._compensate_failed_settlement(
        _DB(), FIRM, CLIENT, "failed-receipt-id", "journal-own-456",
        {"id": "u1"}, [],
    )

    assert reversed_calls == ["journal-own-456"]
    assert table.deleted_ids == ["failed-receipt-id"]


class _PaymentsTableForCompensation:
    def __init__(self, existing_owner_id):
        self._existing_owner_id = existing_owner_id

    def select(self, *_a, **_k):
        return self

    def eq(self, *_a, **_k):
        return self

    def limit(self, *_a, **_k):
        return self

    def execute(self):
        data = [{"id": self._existing_owner_id}] if self._existing_owner_id else []
        return SimpleNamespace(data=data)


def test_payment_collision_skips_reversal_when_journal_owned_by_another_payment(monkeypatch):
    """Same CONFIRMED finding, purchase-payments side: a losing request must
    not reverse a journal another already-committed payment owns."""
    import routers.purchase_payments as mod
    import services.phase2_journal_service as journal_mod

    reversed_calls = []
    monkeypatch.setattr(
        journal_mod.phase2_journal_service, "reverse_entry",
        lambda *a, **k: reversed_calls.append(a),
    )

    owned_table = _PaymentsTableForCompensation(existing_owner_id="other-payment-id")

    class _DB:
        def table(self, _name):
            return owned_table

    class _RaisingInsertDB:
        """First .table() call is the failing insert; subsequent calls are the
        ownership-check SELECT — both go through 'purchase_payments' in real
        code, so route by call count."""
        def __init__(self):
            self._n = 0

        def table(self, _name):
            self._n += 1
            if self._n == 1:
                return _RaisingTable(RuntimeError(
                    'duplicate key value violates unique constraint "purchase_payments_firm_payment_no_key"'
                ))
            return owned_table

    with pytest.raises(HTTPException) as exc_info:
        mod._insert_payment_or_compensate(
            _RaisingInsertDB(), "firm-1", {"payment_no": "VPMT-2526-0001"}, "journal-shared-xyz", "user-1",
        )

    assert exc_info.value.status_code == 409
    assert reversed_calls == [], "must NOT reverse a journal another payment already owns"


def test_payment_no_journal_id_skips_reversal_call(monkeypatch):
    """If no journal was posted (journal_entry_id falsy), there's nothing to
    reverse — must not call reverse_entry at all."""
    import routers.purchase_payments as mod
    import services.phase2_journal_service as journal_mod

    reversed_calls = []
    monkeypatch.setattr(
        journal_mod.phase2_journal_service, "reverse_entry",
        lambda db, firm_id, entry_id, *a, **k: reversed_calls.append((firm_id, entry_id)),
    )

    class _DB:
        def table(self, _name):
            return _RaisingTable(RuntimeError("duplicate key value violates unique constraint"))

    with pytest.raises(HTTPException):
        mod._insert_payment_or_compensate(
            _DB(), "firm-1", {"payment_no": "VPMT-2526-0001"}, None, "user-1",
        )

    assert reversed_calls == []


# ─── services/phase2_journal_service.py: journal_for_purchase_payment must ──
# ─── re-raise, matching journal_for_receipt's F7 hardening ──────────────────

def test_journal_for_purchase_payment_reraises_instead_of_swallowing(monkeypatch):
    """CONFIRMED finding: journal_for_purchase_payment used to catch any
    non-ValueError exception and return None, unlike journal_for_receipt
    (hardened under F7 to re-raise). A swallowed posting failure here would
    let the caller mark a vendor payment 'paid' with NO GL journal at all —
    the exact phantom-subledger bug F7 closed for receipts."""
    import services.phase2_journal_service as journal_mod

    monkeypatch.setattr(journal_mod, "_USE_MOCK", False)
    monkeypatch.setattr(
        "core.supabase_client.get_supabase", lambda: object(),
    )
    monkeypatch.setattr(
        journal_mod.phase2_journal_service, "_find_account",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("account lookup failed")),
    )

    with pytest.raises(RuntimeError):
        journal_mod.phase2_journal_service.journal_for_purchase_payment(
            {"payment_no": "VPMT-2526-0001", "payment_date": "2026-04-05", "amount_paise": 10000},
            "firm-1", "client-1",
        )
