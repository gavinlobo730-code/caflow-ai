"""
R2.9 — a receipt_no unique-constraint collision (migration 159), on the
receipt path that still posts its journal BEFORE the number-bearing insert
(the fallback for a client with no `rpc`), must reverse the already-posted
journal rather than leave a phantom GL entry (F7/R1.6's journal-first
ordering). A supplier payment used to be the other half of this file; it is
one database transaction since POST-A-575 and has nothing to reverse. Before this
milestone the insert could never fail this way (no constraint existed);
adding the constraint without this compensation would have silently
reintroduced the exact "phantom journal, no sub-ledger row" bug class F7
fixed for the allocation step — just one step earlier, at the insert itself.

Runs everywhere (mock-mode style, no real database — the real-Postgres
proof of the constraint itself lives in test_debit_note_receipt_and_payment_numbers_are_unique_pg.py).
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


class _CustomerTable(_EmptyTable):
    """task #227: create_receipt_core now requires the customer to be found in
    THIS firm+client's books before it will post anything — this test is
    about the LATER receipt-insert collision, so the customer lookup must
    resolve, not the empty-everything default."""

    def execute(self):
        return SimpleNamespace(data=[{"id": CUSTOMER, "firm_id": FIRM, "client_id": CLIENT, "is_active": True}])


def _fake_db(insert_error):
    receipts = _RaisingReceiptsTable(insert_error)
    customers = _CustomerTable()

    class _DB:
        def table(self, name):
            if name == "receipts":
                return receipts
            if name == "customers":
                return customers
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


# ─── a supplier payment: nothing to compensate since POST-A-575 ─────────────
# `routers/purchase_payments._insert_payment_or_compensate` posted the entry first and reversed it when the payment's insert failed on
# a number collision. A payment's entry, row and bill settlements are one database transaction now (`settle_payment_atomic`, migration
# 784), so a collision leaves nothing to reverse and is answered by taking the next number. What replaced the four tests that stood
# here is in tests/test_a_supplier_payment_is_one_database_transaction.py (the number taken again, a number carried elsewhere, an
# error that is not a known refusal) and, against Postgres, in tests/test_784_a_supplier_payment_is_recorded_in_one_transaction_pg.py.


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
