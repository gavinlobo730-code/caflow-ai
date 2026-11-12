"""
`core.db_paging.iter_pages` is `fetch_all` handed back a page at a time (POST-A-205): one implementation, so an export can write a table as it is read
without holding it, and every property `fetch_all` has (keyset order, the short-page stop, the double that cannot page, the stats) holds for both.
"""
from __future__ import annotations

import pytest

from core import db_paging
from core.db_paging import PAGE, fetch_all, iter_pages
from tests._capped_postgrest import CappedDB


def _db(n: int) -> CappedDB:
    return CappedDB({"t": [{"id": f"r{i:05d}", "v": i} for i in range(n)]})


def test_pages_come_one_request_at_a_time_in_key_order_and_make_the_whole_table():
    db = _db(2 * PAGE + 17)
    pages = list(iter_pages(lambda: db.table("t").select("*"), "id"))
    assert [len(p) for p in pages] == [PAGE, PAGE, 17]
    assert [r["id"] for p in pages for r in p] == [f"r{i:05d}" for i in range(2 * PAGE + 17)]
    assert len(db.requests["t"]) == 3


def test_fetch_all_is_the_pages_put_together_and_fills_the_same_stats():
    db = _db(PAGE + 5)
    paged, whole = {}, {}
    rows = fetch_all(lambda: db.table("t").select("*"), "id", stats=whole)
    list(iter_pages(lambda: db.table("t").select("*"), "id", stats=paged))
    assert len(rows) == PAGE + 5 and paged == whole == {"pages": 2, "rows": PAGE + 5}


def test_stats_are_filled_only_when_the_pages_have_all_been_read():
    db = _db(PAGE + 5)
    stats: dict = {}
    pages = iter_pages(lambda: db.table("t").select("*"), "id", stats=stats)
    next(pages)
    assert stats == {}
    list(pages)
    assert stats["rows"] == PAGE + 5


def test_a_table_of_exactly_one_page_costs_a_second_request_and_yields_no_empty_page():
    db = _db(PAGE)
    pages = list(iter_pages(lambda: db.table("t").select("*"), "id"))
    assert [len(p) for p in pages] == [PAGE] and len(db.requests["t"]) == 2


def test_an_empty_table_yields_nothing():
    assert list(iter_pages(lambda: _db(0).table("t").select("*"), "id")) == []


def test_a_query_that_cannot_page_is_read_once_as_one_page():
    class Plain:
        def __init__(self):
            self.n = 0

        def execute(self):
            self.n += 1

            class R:
                data = [{"id": "a"}, {"id": "b"}]
            return R()
    plain = Plain()
    assert list(iter_pages(lambda: plain, "id")) == [[{"id": "a"}, {"id": "b"}]] and plain.n == 1


def test_a_cursor_that_does_not_advance_stops_loudly(monkeypatch, caplog):
    monkeypatch.setattr(db_paging, "MAX_PAGES", 2)
    db = _db(5 * PAGE)
    pages = list(iter_pages(lambda: db.table("t").select("*"), "id", label="stuck"))
    assert len(pages) == 2
    assert any("hit the 2-page cap" in r.message for r in caplog.records)


@pytest.mark.parametrize("n", [0, 1, PAGE - 1, PAGE, PAGE + 1, 3 * PAGE])
def test_fetch_all_still_returns_every_row(n):
    assert len(fetch_all(lambda: _db(n).table("t").select("*"), "id")) == n
