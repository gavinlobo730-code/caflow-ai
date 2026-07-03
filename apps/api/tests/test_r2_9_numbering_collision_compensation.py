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
    def __init__(self, error):
        self._error = error

    def insert(self, *_a, **_k):
        return self

    def execute(self):
        raise self._error


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
