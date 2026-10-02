"""One pager, and a read that pages is shown paging (engineering-30).

WHAT WAS WRONG
    `core/db_paging.fetch_all` is the repository's one sanctioned pager, and CLAUDE.md said so while
    twelve services went on carrying a private copy of the same keyset loop: "eleven modules still
    carry a private copy, adding a twelfth is the thing not to do", and a twelfth had been added. A bug
    fixed in the shared loop (it logs and stops when a row has no cursor; it has a page cap) stayed alive
    in the copies, and every copy that omitted the cap could loop for ever on a query that ignored its
    cursor.

    Nine of the twelve carried one more thing, and it is why they were not simply deleted: a hand-written
    test double that implements `.eq()` and `.execute()` and nothing else returns its whole, small fixture
    from one `execute()`, which is already right, and has no `.gt` / `.order` / `.limit` to page with. That
    tolerance now lives in `fetch_all` itself, once, said as test-double accommodation, and is pinned below.

THE RULE, NOT A LIST OF TODAY'S MODULES
    A function that pages a query by hand is a loop that calls `.execute()` together with either `.gt()` and
    `.limit()` (keyset) or `.range()` (offset). The scan finds that SHAPE in every module of the application,
    so a pager written next year under any name is found. The shapes that survive are a frozen list with the
    reason each could not simply call `fetch_all`; the list may only shrink, and an entry whose function no
    longer pages by hand fails as loudly as a new pager does, so a fix cannot leave its exemption behind.

WHAT IS NOT CLAIMED
    That the ten survivors are right to survive. Four of them are plain keyset walks over `id` that
    `fetch_all` could do (marked "could move"); the five OFFSET ones page in a caller-chosen order that
    `fetch_all`, which imposes ORDER BY id, cannot give them. Moving the first four is a refactor of
    statutory reads with their own tests, and is named here rather than done under another finding's id.
"""
from __future__ import annotations

import ast
import datetime as dt
import logging
from pathlib import Path

import pytest

from core import db_paging

API = Path(__file__).resolve().parents[1]
SKIP = {"tests", "migrations", "__pycache__", ".venv", "venv"}


# ═══ The rule ════════════════════════════════════════════════════════════════════════════════════════════════════

def _attribute_calls(node: ast.AST) -> set[str]:
    return {n.func.attr for n in ast.walk(node) if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}


def hand_rolled_pagers(source: str) -> list[tuple[str, str]]:
    """(function name, 'keyset' | 'offset') for every function holding a loop that pages a query by hand."""
    found: list[tuple[str, str]] = []
    for fn in ast.walk(ast.parse(source)):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for loop in ast.walk(fn):
            if not isinstance(loop, (ast.While, ast.For)):
                continue
            calls = _attribute_calls(loop)
            if {"gt", "limit", "execute"} <= calls:
                found.append((fn.name, "keyset"))
                break
            if {"range", "execute"} <= calls:
                found.append((fn.name, "offset"))
                break
    return found


def _tree() -> dict[tuple[str, str], str]:
    out: dict[tuple[str, str], str] = {}
    for path in sorted(API.rglob("*.py")):
        rel = path.relative_to(API)
        if rel.parts[0] in SKIP or str(rel) == "core/db_paging.py":
            continue
        text = path.read_text(encoding="utf-8")
        if ".execute()" not in text:                       # cheap prefilter: most modules never touch a query
            continue
        for name, kind in hand_rolled_pagers(text):
            out[(rel.as_posix(), name)] = kind
    return out


#: Every hand-rolled pager that remains, and why it is not a call to `fetch_all`. Shrink-only.
FROZEN: dict[tuple[str, str], str] = {
    ("domain/reporting/sources.py", "_fetch_page"):
        "keyset with a retry and back-off per page (`max_retries`): the ledger source retries a transient "
        "failure on page N, which fetch_all does not",
    ("services/bank_exception_service.py", "_seen_before"):
        "keyset over a SHRINKING IN list that stops as soon as every wanted value is seen, with a page cap "
        "whose hit is the answer ('complete' is False)",
    ("domain/tally/migration_service.py", "_all_items"):
        "could move: keyset over `id` with a caller-chosen projection; no test of its own drives it past a page",
    ("services/itc_reversal_service.py", "_all_bills"):
        "could move: keyset over `id`, with the carried-over filter applied per page",
    ("services/itc_reversal_service.py", "_note_adjustments"):
        "could move: two keyset walks, written out as literal blocks so the column guard reads each table name",
    ("domain/inventory_service.py", "get_stock_ledger"):
        "OFFSET in (movement_date, created_at) order: the stored running totals were chained in that order and "
        "the display must keep it (its own comment); fetch_all imposes ORDER BY id",
    ("routers/inventory.py", "_last_ledger_rows"):
        "OFFSET in created_at DESC order over a filter that narrows as items are found (INV-07)",
    ("services/stock_ageing_service.py", "_fetch_movements"):
        "OFFSET in (movement_date, created_at) order, the FIFO walk's own",
    ("services/stock_position_service.py", "_fetch_movements"):
        "OFFSET in (movement_date, created_at) order, the position's own",
    ("routers/tds_workspace.py", "_paginate_deductions"):
        "could move: OFFSET over `id`, which is exactly what fetch_all does by keyset",
}


def test_the_detector_finds_a_keyset_loop_an_offset_loop_and_nothing_else():
    keyset = ("def f(db):\n    cursor = None\n    while True:\n        q = db.table('t').select('id')\n"
              "        if cursor: q = q.gt('id', cursor)\n        rows = q.order('id').limit(10).execute().data\n"
              "        if len(rows) < 10: return rows\n")
    offset = ("def g(db):\n    for i in range(5):\n        rows = db.table('t').select('*').range(i, i + 9).execute().data\n")
    one_read = "def h(db):\n    return db.table('t').select('id').limit(10).execute().data\n"
    shared = "def k(db):\n    return fetch_all(lambda: db.table('t').select('id'))\n"
    loop_without_paging = "def m(db, ids):\n    for i in ids:\n        db.table('t').select('id').eq('id', i).execute()\n"
    assert hand_rolled_pagers(keyset) == [("f", "keyset")]
    assert hand_rolled_pagers(offset) == [("g", "offset")]
    assert hand_rolled_pagers(one_read) == hand_rolled_pagers(shared) == hand_rolled_pagers(loop_without_paging) == []


def test_the_scan_finds_the_pagers_that_remain_so_it_is_not_vacuous():
    assert len(_tree()) >= 8, "the tree scan stopped finding hand-rolled pagers; the rule below would pass over nothing"


def test_no_module_pages_a_query_by_hand_except_the_frozen_ones():
    new = sorted(f"{path}::{name} ({kind})" for (path, name), kind in _tree().items() if (path, name) not in FROZEN)
    assert not new, ("a function pages a query by hand. Use core.db_paging.fetch_all (it calls a make_query per "
                     "page, imposes ORDER BY id, and needs the key in the select): " + ", ".join(new))


def test_the_frozen_list_only_shrinks():
    found = _tree()
    gone = sorted(f"{path}::{name}" for path, name in FROZEN if (path, name) not in found)
    assert not gone, f"these no longer page by hand; delete them from FROZEN: {gone}"


# ═══ The twelve that were moved ══════════════════════════════════════════════════════════════════════════════════

MOVED = [
    "services/ageing_schedule_service.py", "services/collections_service.py", "services/vendor_statement_service.py",
    "services/reconciliation_service.py", "services/tds_return_service.py", "services/gst_advance_service.py",
    "services/customer_statement_service.py", "services/gst_return_service.py", "services/fx_reporting_service.py",
    "services/gst_2b_reconciliation_service.py", "services/itc_register_service.py",
    "domain/currency/fx_revaluation_service.py",
]


@pytest.mark.parametrize("rel", MOVED)
def test_each_moved_module_reads_through_the_shared_pager_and_defines_none_of_its_own(rel):
    tree = ast.parse((API / rel).read_text(encoding="utf-8"))
    imported = any(isinstance(n, ast.ImportFrom) and n.module == "core.db_paging"
                   and any(a.name == "fetch_all" for a in n.names) for n in tree.body)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "fetch_all"]
    private = [n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and "paginate" in n.name.lower()]
    assert imported and calls and not private, (rel, imported, len(calls), private)


# ═══ fetch_all itself ════════════════════════════════════════════════════════════════════════════════════════════

class _Result:
    def __init__(self, data):
        self.data = data


class PagingQuery:
    """A PostgREST builder reduced to what paging needs: `gt` and `order` and `limit` on `id`, any other filter
    accepted and ignored (the fixture holds only matching rows), and an `execute` that records what it was asked."""

    def __init__(self, store, name, log):
        self._store, self._name, self._log = store, name, log
        self._cursor, self._limit = None, None

    def __getattr__(self, attr):
        if attr == "not_":
            return self
        return lambda *a, **k: self

    def gt(self, column, value):
        if column == "id":
            self._cursor = value
        return self

    def order(self, *a, **k):
        return self

    def limit(self, n):
        self._limit = n
        return self

    def execute(self):
        rows = sorted(self._store(self._name), key=lambda r: r["id"])
        if self._cursor is not None:
            rows = [r for r in rows if r["id"] > self._cursor]
        if self._limit is not None:
            rows = rows[: self._limit]
        self._log.append((self._name, len(rows), self._limit))
        return _Result([dict(r) for r in rows])


class PagingDB:
    """Every table holds the same `n` rows of generic invoice-shaped data, so one double can stand behind any of the
    services below. The log is the evidence: (table, rows returned, limit asked for) per `execute`."""

    def __init__(self, n=8):
        self.n, self.log = n, []

    def _rows(self, _name):
        return [{"id": f"{i:04d}", "firm_id": "F", "client_id": "C", "status": "issued",
                 "outstanding_paise": 100, "total_paise": 100} for i in range(self.n)]

    def table(self, name):
        return PagingQuery(self._rows, name, self.log)

    def pages(self, table):
        return [n for t, n, _ in self.log if t == table]


@pytest.fixture()
def small_pages(monkeypatch):
    monkeypatch.setattr(db_paging, "PAGE", 3)


def test_fetch_all_reads_every_page_and_stops_on_the_short_one(small_pages):
    db, stats = PagingDB(8), {}
    rows = db_paging.fetch_all(lambda: db.table("t"), stats=stats)
    assert [r["id"] for r in rows] == [f"{i:04d}" for i in range(8)]
    assert db.pages("t") == [3, 3, 2] and stats == {"pages": 3, "rows": 8}
    assert all(limit == 3 for _, _, limit in db.log), "every page must be asked for with the page size"


def test_a_full_last_page_costs_one_more_read_and_loses_no_row(small_pages):
    db = PagingDB(6)
    assert len(db_paging.fetch_all(lambda: db.table("t"))) == 6
    assert db.pages("t") == [3, 3, 0]


class _ExecuteOnly:
    """The hand-written double the nine tolerant copies existed for: `.eq()` and `.execute()`, nothing to page with."""

    def __init__(self, rows):
        self._rows, self.executed = rows, 0

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def execute(self):
        self.executed += 1
        return _Result(self._rows)


def test_a_query_that_cannot_page_is_read_once(small_pages):
    rows, stats = [{"id": str(i)} for i in range(10)], {}
    q = _ExecuteOnly(rows)
    assert db_paging.fetch_all(lambda: q.select("id").eq("a", 1), stats=stats) == rows
    assert q.executed == 1 and stats == {"pages": 1, "rows": 10}


def test_the_tolerance_is_judged_on_the_first_page_only_so_a_real_query_cannot_slip_into_it(small_pages):
    """If a later page's builder lacks `.gt`, that is a bug and must RAISE, not return a truncated read."""
    db = PagingDB(8)
    calls = {"n": 0}

    def make():
        calls["n"] += 1
        return db.table("t") if calls["n"] == 1 else _ExecuteOnly([])

    with pytest.raises(AttributeError):
        db_paging.fetch_all(make)


def test_a_last_row_without_the_key_stops_the_read_and_says_so(small_pages, caplog):
    class Keyless(PagingQuery):
        def execute(self):
            self._log.append((self._name, 3, self._limit))
            return _Result([{"other": 1}] * 3)

    db = PagingDB()
    with caplog.at_level(logging.ERROR, logger="caflow.db.paging"):
        rows = db_paging.fetch_all(lambda: Keyless(db._rows, "t", db.log))
    assert len(rows) == 3 and "last row has no `id`" in caplog.text


# ═══ The services that paged privately now page through it ═══════════════════════════════════════════════════════
#
# "A service whose job is to FETCH needs a test that fetches": the reorder report was never run against a
# database for the lack of one. Each case drives a real read function of a moved module with the double above at
# a page size of three over eight rows, and asserts on the double's own log (three pages, the last short) and, where
# the function hands rows back, on all eight arriving. The customer and vendor statements are driven past a page by
# test_statement_aging_scale.py already.

def _cases():
    from domain.currency import fx_revaluation_service as fxv
    from services import (ageing_schedule_service as ags, collections_service as col, fx_reporting_service as fxr,
                          gst_2b_reconciliation_service as g2b, gst_advance_service as adv,
                          gst_return_service as grs, itc_register_service as itc,
                          reconciliation_service as rec, tds_return_service as trs)
    as_of = dt.date(2026, 3, 31)
    return {
        "ageing_schedule._fetch_receivables": (lambda db: ags._fetch_receivables(db, "F", "C", as_of),
                                               "client_sales_invoices", 8),
        "ageing_schedule._fetch_payables": (lambda db: ags._fetch_payables(db, "F", "C", as_of),
                                            "purchase_bills", 8),
        "itc_register.for_periods": (lambda db: itc.for_periods(db, "F", "C", ["042025"]),
                                     "itc_reversal_register", None),
        "gst_return._posted_sales": (lambda db: grs._posted_sales(db, "F", "C", "2025-04-01", "2025-04-30"),
                                     "client_sales_invoices", 8),
        "tds_return._deposited_challans": (lambda db: trs._deposited_challans(db, "F", "C", "2025-26", "Q1"),
                                           "tds_challans", 8),
        "gst_2b.read_book_bills": (lambda db: g2b.read_book_bills(db, "F", "C", "042025"), "purchase_bills", 8),
        "fx_reporting._entry_dates": (lambda db: fxr.FXReportingService()._entry_dates(db, "F", "C"),
                                      "journal_entries", 8),
        "fx_revaluation._open_receivables": (
            lambda db: fxv.FXRevaluationService()._open_receivables(db, "F", "C", as_of),
            "client_sales_invoices", None),
        "reconciliation.check_missing_cogs_journals": (
            lambda db: rec.check_missing_cogs_journals(db, "F", "C", []), "inventory_stock_ledger", None),
        "gst_advance.advances_report": (lambda db: adv.advances_report(db, "F", "C", "042025"), "receipts", None),
        "collections._open_invoices": (lambda db: col._open_invoices("F", "C"), None, 8),
    }


@pytest.mark.parametrize("name", sorted(_cases()))
def test_a_service_that_paged_privately_reads_every_row_through_the_one_pager(name, small_pages, monkeypatch):
    from services import collections_service as col
    call, table, expected = _cases()[name]
    db = PagingDB(8)
    if name.startswith("collections."):
        monkeypatch.setattr(col, "_USE_MOCK", False)
        monkeypatch.setattr(col, "_db", lambda: db)
    out = call(db)
    if table is not None:
        assert db.pages(table) == [3, 3, 2], f"{name}: {db.log}"
    if expected is not None:
        assert len(out) == expected, f"{name} handed back {len(out)} of 8 rows"
