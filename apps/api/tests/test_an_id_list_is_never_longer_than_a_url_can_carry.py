"""`fetch_all_in` sends an IN list in pieces a URL can carry, and loses no row.

The §43B(h) report put every one of a client's purchase bill ids into ONE
`.in_("purchase_bill_id", ...)` filter. PostgREST filters travel in the URL,
so for Apex Trading (755 bills) the request was 29,651 characters and the
gateway refused it with a 400 before PostgREST saw it — the report 500'd for
every financial year, and Form 3CD clauses 22/26 and the book-to-tax add-back,
which both read it, silently lost their figure.
"""
from __future__ import annotations

import uuid

from core import db_paging
from core.db_paging import IN_CHUNK, fetch_all_in


class _Query:
    """Just enough of a PostgREST builder for fetch_all: records the IN list
    it was sent and answers from a fixed table, keyset-paged on `id`."""

    def __init__(self, rows, log):
        self._rows, self._log = rows, log
        self._in = None
        self._gt = None
        self._limit = None

    def in_(self, column, values):
        self._in = (column, list(values))
        return self

    def gt(self, key, cursor):
        self._gt = (key, cursor)
        return self

    def order(self, key):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        column, values = self._in
        self._log.append(values)
        wanted = set(values)
        rows = sorted((r for r in self._rows if r[column] in wanted), key=lambda r: r["id"])
        if self._gt:
            rows = [r for r in rows if r["id"] > self._gt[1]]
        rows = rows[: self._limit]

        class _R:
            data = rows
        return _R()


def _table(n_bills: int, per_bill: int = 2):
    bills = [str(uuid.UUID(int=i + 1)) for i in range(n_bills)]
    rows = [{"id": f"{b}-{k}", "purchase_bill_id": b}
            for b in bills for k in range(per_bill)]
    return bills, rows


def test_a_long_list_is_sent_in_pieces_no_longer_than_the_chunk():
    bills, rows = _table(755)
    log: list = []
    got = fetch_all_in(lambda: _Query(rows, log), "purchase_bill_id", bills)
    assert log, "nothing was requested"
    assert max(len(v) for v in log) <= IN_CHUNK
    assert len(log) == -(-755 // IN_CHUNK)


def test_every_row_comes_back_exactly_once():
    bills, rows = _table(755)
    got = fetch_all_in(lambda: _Query(rows, []), "purchase_bill_id", bills)
    assert sorted(r["id"] for r in got) == sorted(r["id"] for r in rows)


def test_a_chunk_matching_more_than_a_page_is_still_paged(monkeypatch):
    # Each chunk goes through fetch_all, so a chunk whose rows exceed one page
    # keeps paging rather than stopping at the server's row cap.
    monkeypatch.setattr(db_paging, "PAGE", 7)
    bills, rows = _table(20, per_bill=3)
    got = fetch_all_in(lambda: _Query(rows, []), "purchase_bill_id", bills, chunk=10)
    assert len(got) == 60


def test_duplicates_and_nones_are_not_sent():
    bills, rows = _table(3)
    log: list = []
    fetch_all_in(lambda: _Query(rows, log), "purchase_bill_id",
                 bills + bills + [None])
    assert log == [sorted(bills)]


def test_an_empty_list_asks_nothing():
    log: list = []
    assert fetch_all_in(lambda: _Query([], log), "purchase_bill_id", []) == []
    assert log == []


def test_premise_one_list_of_every_bill_is_longer_than_a_url_should_be():
    # The failing request carried 755 uuids; this is its IN list's own length.
    bills, _ = _table(755)
    assert len(",".join(f'"{b}"' for b in bills)) > 28_000
    assert len(",".join(f'"{b}"' for b in bills[:IN_CHUNK])) < 6_000


def test_the_43bh_payments_read_uses_it_for_every_id_list():
    import inspect
    from services import msme_43bh_service as svc
    src = inspect.getsource(svc._payments)
    assert src.count("fetch_all_in(") == 3
    assert ".in_(" not in src
