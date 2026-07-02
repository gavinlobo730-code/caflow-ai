"""
R1.1 — unit coverage of the per-client sequence generators (finding F6).

The real-Postgres proof (test_per_client_numbering.py) shows the widened UNIQUE
constraint lets two clients share a number. This complements it by exercising the
APPLICATION numbering path itself: _next_invoice_seq / _next_cn_seq must scope
their count by client_id, so a fresh client always starts at 1 regardless of how
many invoices sibling clients of the same firm already have. If either ever
regressed to a per-firm count, the second client would resume mid-series (and,
before 151, collide) — this test locks the per-client property. Runs everywhere
(no database needed).
"""
from __future__ import annotations

from types import SimpleNamespace

from routers.sales_invoices import _next_invoice_seq
from routers.credit_notes import _next_cn_seq


class _FakeQuery:
    """Minimal supabase-py query stub: records .eq() filters and counts matching
    rows from an in-memory store, emulating select(count='exact')."""

    def __init__(self, store: list[dict], number_field: str):
        self._store = store
        self._number_field = number_field
        self._eq: dict[str, str] = {}
        self._like_prefix: str | None = None

    def select(self, *_a, **_k):
        return self

    def eq(self, col: str, val):
        self._eq[col] = val
        return self

    def like(self, col: str, pattern: str):
        assert col == self._number_field
        self._like_prefix = pattern.rstrip("%")
        return self

    def execute(self):
        rows = [
            r for r in self._store
            if all(r.get(k) == v for k, v in self._eq.items())
            and (self._like_prefix is None or str(r.get(self._number_field, "")).startswith(self._like_prefix))
        ]
        return SimpleNamespace(count=len(rows), data=rows)


class _FakeDB:
    def __init__(self, store: list[dict], number_field: str):
        self._store = store
        self._number_field = number_field

    def table(self, _name: str):
        return _FakeQuery(self._store, self._number_field)


FIRM = "firm-1"
CLIENT_A = "client-A"
CLIENT_B = "client-B"


def test_next_invoice_seq_is_scoped_per_client():
    # Client A already has three FY-2526 invoices; client B has none.
    store = [
        {"firm_id": FIRM, "client_id": CLIENT_A, "invoice_no": f"SINV-2526-000{i}"}
        for i in (1, 2, 3)
    ]
    db = _FakeDB(store, "invoice_no")

    # Client A's next number continues its own series...
    assert _next_invoice_seq(db, FIRM, CLIENT_A, "2526") == 4
    # ...while a brand-new client of the SAME firm starts at 1 (the F6 property).
    assert _next_invoice_seq(db, FIRM, CLIENT_B, "2526") == 1


def test_next_invoice_seq_isolates_by_financial_year():
    store = [{"firm_id": FIRM, "client_id": CLIENT_A, "invoice_no": "SINV-2425-0009"}]
    db = _FakeDB(store, "invoice_no")
    # A prior-FY invoice must not bump the current FY's sequence.
    assert _next_invoice_seq(db, FIRM, CLIENT_A, "2526") == 1


def test_next_cn_seq_is_scoped_per_client():
    store = [
        {"firm_id": FIRM, "client_id": CLIENT_A, "credit_note_no": "CN-2526-0001"},
        {"firm_id": FIRM, "client_id": CLIENT_A, "credit_note_no": "CN-2526-0002"},
    ]
    db = _FakeDB(store, "credit_note_no")
    assert _next_cn_seq(db, FIRM, CLIENT_A, "2526") == 3
    assert _next_cn_seq(db, FIRM, CLIENT_B, "2526") == 1
