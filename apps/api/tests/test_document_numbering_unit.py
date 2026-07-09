"""
R1.1 — unit coverage of the per-client sequence generator (finding F6).

The real-Postgres proof (test_per_client_numbering.py) shows the widened UNIQUE
constraint lets two clients share a number. This complements it by exercising the
APPLICATION numbering path itself: _next_cn_seq must scope its count by
client_id, so a fresh client always starts at 1 regardless of how many credit
notes sibling clients of the same firm already have. If it ever regressed to a
per-firm count, the second client would resume mid-series (and, before 151,
collide) — this test locks the per-client property. Runs everywhere (no
database needed).

Sales invoices no longer have an application-level sequence generator to test
here — invoice numbering is fully manual (the CA types it; Caflow only
validates shape + per-client uniqueness, see routers/sales_invoices.py's
_assert_invoice_no_available). The widened UNIQUE constraint itself (migration
151) still applies to sales invoices too and remains covered by
test_per_client_numbering.py's real-Postgres proof.
"""
from __future__ import annotations

from types import SimpleNamespace

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


def test_next_cn_seq_is_scoped_per_client():
    store = [
        {"firm_id": FIRM, "client_id": CLIENT_A, "credit_note_no": "CN-2526-0001"},
        {"firm_id": FIRM, "client_id": CLIENT_A, "credit_note_no": "CN-2526-0002"},
    ]
    db = _FakeDB(store, "credit_note_no")
    assert _next_cn_seq(db, FIRM, CLIENT_A, "2526") == 3
    assert _next_cn_seq(db, FIRM, CLIENT_B, "2526") == 1
