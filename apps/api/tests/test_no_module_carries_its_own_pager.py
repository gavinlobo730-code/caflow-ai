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

WHAT IS LEFT
    Nothing. The four plain keyset walks moved onto `fetch_all` on 28-10-2026, and on 14-11-2026 (POST-A-045) the
    shared pager learned what the next five needed: a retry per page (the reporting source), a query built
    afresh for every page so an IN list can shrink (the bank history), and an ordered OFFSET read whose order
    ends in `id` (the three readers of stock movements, which page in (movement_date, created_at) order; ending
    it in `id` is also what stops a movement that ties on both from being read twice or never). The last, the
    stock register's latest row per item, is one question to the database since POST-A-435, so the list is empty.
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
    # EMPTY since 14-11-2026. Five left with POST-A-045 (the reporting source's retrying keyset, the bank history's shrinking IN list,
    # the three readers of stock movements in (movement_date, created_at) order) and the sixth, the stock register's latest row per
    # item, became one question to the database with POST-A-435 (`public.stock_latest_rows`, migration 588).
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


def _modules_scanned() -> int:
    return sum(1 for path in API.rglob("*.py") if path.relative_to(API).parts[0] not in SKIP
               and str(path.relative_to(API)) != "core/db_paging.py" and ".execute()" in path.read_text(encoding="utf-8"))


def test_the_scan_reads_the_application_so_it_is_not_vacuous():
    """Counting the pagers it finds stopped being the measure once nearly all of them moved (POST-A-045): the scan must read the modules
    that query the database (the detector's own test above proves it recognises both shapes when it reads them)."""
    assert _modules_scanned() >= 150, "the tree scan stopped reading the modules that query the database; the rule would pass over nothing"


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


# ═══ What the shared pager learned for the five that moved (POST-A-045) ═══════════════════════════════════════════

class OrderedQuery:
    """A builder that honours `.order()` terms in the sequence given and `.range()`, and returns rows that TIE on every term in an order
    of its own that changes from request to request, as Postgres may. That freedom is exactly what makes an OFFSET read without a total
    order read a row twice or never."""

    def __init__(self, rows, log, seed):
        self._rows, self._log, self._seed = rows, log, seed
        self._terms: list[tuple[str, bool]] = []
        self._range = None

    def select(self, *a, **k):
        return self

    def eq(self, *a, **k):
        return self

    def order(self, column, desc=False):
        self._terms.append((column, desc))
        return self

    def range(self, start, end):
        self._range = (start, end)
        return self

    def execute(self):
        import random
        rows = [dict(r) for r in self._rows]
        random.Random(self._seed).shuffle(rows)              # the arrival order of rows that tie on every term
        for column, desc in reversed(self._terms):           # a stable sort per term, last term first
            rows.sort(key=lambda r: r[column], reverse=desc)
        start, end = self._range
        self._log.append((tuple(self._terms), start, end))
        return _Result(rows[start:end + 1])


def _movements():
    """Ten movements, seven of which share the date and the recorded-at instant (an opening batch is one statement)."""
    tie = [{"id": f"m{i:02d}", "movement_date": "2025-04-01", "created_at": "2025-04-01T10:00:00+00:00"} for i in range(7)]
    rest = [{"id": "a01", "movement_date": "2025-03-31", "created_at": "2025-04-01T09:00:00+00:00"},
            {"id": "z01", "movement_date": "2025-04-02", "created_at": "2025-04-02T09:00:00+00:00"},
            {"id": "b01", "movement_date": "2025-04-01", "created_at": "2025-04-01T11:00:00+00:00"}]
    return tie + rest


def _requests(rows):
    """A make_query whose every request is a fresh builder with its own arrival order."""
    log, n = [], {"i": 0}

    def make():
        n["i"] += 1
        return OrderedQuery(rows, log, seed=n["i"])
    return make, log


def test_an_ordered_read_ends_its_order_in_id_and_reads_every_tied_row_exactly_once():
    rows = _movements()
    make, log = _requests(rows)
    got = db_paging.fetch_all_ordered(make, ("movement_date", "created_at"), page_size=3)
    assert [r["id"] for r in got] == ["a01", *[f"m{i:02d}" for i in range(7)], "b01", "z01"]
    assert all(terms == (("movement_date", False), ("created_at", False), ("id", False)) for terms, _, _ in log)
    assert [(s, e) for _, s, e in log] == [(0, 2), (3, 5), (6, 8), (9, 11)]


def test_without_the_id_the_same_offset_read_loses_or_repeats_a_tied_row():
    """The negative control: the loop the four stock readers carried, over the same double, is wrong for some arrival order."""
    rows = _movements()

    def old_loop(seed0):
        out, offset, n = [], 0, 0
        while True:
            n += 1
            page = (OrderedQuery(rows, [], seed=seed0 + n).order("movement_date").order("created_at")
                    .range(offset, offset + 2).execute().data)
            out.extend(page)
            if len(page) < 3:
                return out
            offset += 3

    wrong = [s for s in range(20) if sorted(r["id"] for r in old_loop(s)) != sorted(r["id"] for r in rows)]
    assert wrong, "the double never produced the fault, so the test above would pass without the tie-break"


def test_an_ordered_read_keeps_a_descending_term_and_does_not_add_id_twice():
    rows = _movements()
    make, log = _requests(rows)
    got = db_paging.fetch_all_ordered(make, (("created_at", True), "id"), page_size=4)
    assert log[0][0] == (("created_at", True), ("id", False))
    assert [r["id"] for r in got][:2] == ["z01", "b01"] and len(got) == len(rows) == len({r["id"] for r in got})


def test_an_ordered_read_of_a_builder_that_cannot_page_is_read_once():
    rows, stats = [{"id": str(i)} for i in range(5)], {}
    q = _ExecuteOnly(rows)
    assert db_paging.fetch_all_ordered(lambda: q.select("id").eq("a", 1), ("movement_date",), stats=stats) == rows
    assert q.executed == 1 and stats == {"pages": 1, "rows": 5}


class _FailsOnce(PagingQuery):
    """Raises on the first execute of the page after `fail_after`, then behaves."""

    failures: dict = {}

    def execute(self):
        if self._cursor == "0002" and not _FailsOnce.failures.get("done"):
            _FailsOnce.failures["done"] = True
            raise RuntimeError("transient 500")
        return super().execute()


def test_a_failed_page_is_asked_again_with_a_growing_wait_and_every_row_arrives(small_pages, monkeypatch):
    waits = []
    monkeypatch.setattr(db_paging, "_sleep", waits.append)
    _FailsOnce.failures = {}
    db = PagingDB(8)
    rows = db_paging.fetch_all(lambda: _FailsOnce(db._rows, "t", db.log), retries=3)
    assert [r["id"] for r in rows] == [f"{i:04d}" for i in range(8)] and waits == [db_paging.RETRY_BACKOFF_SECONDS]


def test_one_attempt_raises_the_failure_as_it_came_and_waits_for_nothing(small_pages, monkeypatch):
    waits = []
    monkeypatch.setattr(db_paging, "_sleep", waits.append)
    _FailsOnce.failures = {}
    db = PagingDB(8)
    with pytest.raises(RuntimeError, match="transient 500"):
        db_paging.fetch_all(lambda: _FailsOnce(db._rows, "t", db.log))
    assert waits == []


def test_a_page_that_keeps_failing_raises_its_last_failure_after_every_attempt(small_pages, monkeypatch, caplog):
    waits, attempts = [], {"n": 0}
    monkeypatch.setattr(db_paging, "_sleep", waits.append)

    class Down(PagingQuery):
        def execute(self):
            attempts["n"] += 1
            raise RuntimeError(f"down {attempts['n']}")

    db = PagingDB(8)
    with caplog.at_level(logging.ERROR, logger="caflow.db.paging"), pytest.raises(RuntimeError, match="down 3"):
        db_paging.fetch_all(lambda: Down(db._rows, "t", db.log), retries=3, label="t")
    assert attempts["n"] == 3 and waits == [0.3, 0.6] and "after 3 attempts" in caplog.text


def test_the_reporting_source_reads_through_the_shared_pager_with_its_retry(monkeypatch):
    """The ledger source's own retry moved into the pager: a page that fails once is asked again, and the report gets every row."""
    from domain.reporting import sources
    monkeypatch.setattr(db_paging, "_sleep", lambda s: None)
    monkeypatch.setattr(sources.SupabaseLedgerSource, "_PAGE", 3)
    _FailsOnce.failures = {}
    db = PagingDB(8)
    src = sources.SupabaseLedgerSource.__new__(sources.SupabaseLedgerSource)
    stats: dict = {}
    rows = src._fetch_all(lambda: _FailsOnce(db._rows, "journal_entries", db.log), stats=stats)
    assert len(rows) == 8 and stats["pages"] == 3 and stats["rows"] == 8 and "seconds" in stats
    assert not hasattr(sources.SupabaseLedgerSource, "_fetch_page"), "the private page reader is gone"


def test_a_query_built_afresh_each_page_may_narrow_its_filter_and_the_cursor_stays_true(small_pages):
    """The bank history's shape: each page asks only for the values not yet seen."""
    asked, seen = [], set()

    class Narrowing(PagingQuery):
        def in_(self, column, values):
            asked.append(tuple(values))
            self._wanted = set(values)
            return self

        def execute(self):
            rows = [r for r in sorted(self._store(self._name), key=lambda r: r["id"]) if r["x"] in self._wanted]
            if self._cursor is not None:
                rows = [r for r in rows if r["id"] > self._cursor]          # the server filters, seeks, then limits
            rows = rows[: self._limit]
            self._log.append((self._name, len(rows), self._limit))
            return _Result([dict(r) for r in rows])

    letters = "aabbbcccd"
    db = PagingDB(len(letters))
    rows = [{**r, "x": letters[i]} for i, r in enumerate(db._rows("t"))]
    pages = []
    for page in db_paging.iter_pages(lambda: Narrowing(lambda _n: rows, "t", db.log).in_("x", sorted({"a", "b", "c", "d"} - seen))):
        pages.append([r["id"] for r in page])
        seen.update(r["x"] for r in page)
    assert asked == [("a", "b", "c", "d"), ("c", "d"), ("d",)], "page one built more than once, or the list did not narrow"
    flat = [i for p in pages for i in p]
    assert len(flat) == len(set(flat)) and seen == set(letters), "the cursor skipped or repeated a row under the narrower filter"


# ── what the independent read of POST-A-045 asked for ────────────────────────────────────────────────────────────────

class _AnyFilterOrdered(OrderedQuery):
    """OrderedQuery that accepts every other filter a reader chains (eq, lte, in_ ...) and ignores it: the fixture holds only rows
    that match."""

    def __getattr__(self, attr):
        return lambda *a, **k: self


def test_the_three_stock_readers_page_past_one_page_and_read_every_tied_row_once(monkeypatch):
    from domain import inventory_service
    from services import stock_ageing_service, stock_position_service
    rows = [{**r, "service_catalogue_id": "X", "quantity_delta": "1", "value_delta_paise": 1} for r in _movements()]
    expected = ["a01", *[f"m{i:02d}" for i in range(7)], "b01", "z01"]
    monkeypatch.setattr(db_paging, "PAGE", 3)
    monkeypatch.setattr(stock_ageing_service, "_PAGE", 3)
    monkeypatch.setattr(stock_position_service, "_PAGE", 3)
    for read in (lambda db: inventory_service.get_stock_ledger(db, "X", firm_id="F", client_id="C"),
                 lambda db: stock_ageing_service._fetch_movements(db, "F", "C", "2026-03-31"),
                 lambda db: stock_position_service._fetch_movements(db, "F", "C", "2026-03-31")):
        log, n = [], {"i": 0}

        class DB:
            def table(self, _name, log=log, n=n):            # bound now: each reader gets its own log and seed counter
                n["i"] += 1
                return _AnyFilterOrdered(rows, log, seed=n["i"])

        got = read(DB())
        assert [r["id"] for r in got] == expected and [(s, e) for _, s, e in log] == [(0, 2), (3, 5), (6, 8), (9, 11)]


class _History(PagingQuery):
    """The bank history's builder: it honours the IN list on the column it is asked about, as the server would."""

    def __init__(self, store, name, log, values):
        super().__init__(store, name, log)
        self._values, self._in = values, None

    def in_(self, column, values):
        if column == "payee_name":
            self._in = set(values)
        return self

    def execute(self):
        rows = sorted(self._store(self._name), key=lambda r: r["id"])
        if self._in is not None:
            rows = [r for r in rows if r["payee_name"] in self._in]
        if self._cursor is not None:
            rows = [r for r in rows if r["id"] > self._cursor]
        rows = rows[: self._limit]
        self._log.append((tuple(sorted(self._in or ())), len(rows), self._limit))
        return _Result([dict(r) for r in rows])


def _bank_history(monkeypatch, payees):
    from services import bank_exception_service as bes
    log = []
    rows = [{"id": f"{i:04d}", "payee_name": p} for i, p in enumerate(payees)]
    monkeypatch.setattr(bes, "privileged_for", lambda db: db)

    class DB:
        def table(self, name):
            return _History(lambda _n: rows, name, log, None)

    return bes, DB(), log


def test_the_bank_history_pages_with_its_own_page_size_and_narrows_its_list_as_it_finds(monkeypatch):
    monkeypatch.setattr(db_paging, "PAGE", 3)
    bes, db, log = _bank_history(monkeypatch, ["a", "a", "a", "b", "b", "b", "c"])
    seen, complete = bes._seen_before(db, "F", "C", column="payee_name", wanted={"a", "b", "c", "d"}, before="2026-04-01",
                                      bank_account_id=None)
    assert seen == {"a", "b", "c"} and complete is True
    assert [entry[0] for entry in log] == [("a", "b", "c", "d"), ("b", "c", "d"), ("c", "d")], log
    assert all(limit == 3 for _, _, limit in log), "the request size was not the page size the short-page test uses"


def test_the_bank_history_reports_a_cut_off_history_as_incomplete(monkeypatch):
    monkeypatch.setattr(db_paging, "PAGE", 3)
    bes, db, log = _bank_history(monkeypatch, ["a"] * 3 + ["b"] * 3 + ["c"] * 3)
    monkeypatch.setattr(bes, "_HISTORY_PAGE_CAP", 2)
    # Each page is full and finds one new value; the cap is reached with c and z still unanswered.
    assert bes._seen_before(db, "F", "C", column="payee_name", wanted={"a", "b", "c", "z"}, before="2026-04-01",
                            bank_account_id=None) == ({"a", "b"}, False)


def test_a_bank_history_the_pager_stops_early_is_not_called_complete(monkeypatch):
    """A full page whose last row has no id ends the pager's read; that is not the end of the history."""
    monkeypatch.setattr(db_paging, "PAGE", 3)
    bes, db, log = _bank_history(monkeypatch, ["a", "a", "a", "f"])
    real_execute = _History.execute

    def keyless_last(self):
        res = real_execute(self)
        if res.data:
            res.data[-1].pop("id", None)
        return res

    monkeypatch.setattr(_History, "execute", keyless_last)
    seen, complete = bes._seen_before(db, "F", "C", column="payee_name", wanted={"a", "f"}, before="2026-04-01",
                                      bank_account_id=None)
    assert complete is False and "f" not in seen


def test_a_page_that_fails_twice_waits_longer_the_second_time(small_pages, monkeypatch):
    waits, failures = [], {"n": 0}
    monkeypatch.setattr(db_paging, "_sleep", waits.append)

    class TwiceDown(PagingQuery):
        def execute(self):
            if self._cursor == "0002" and failures["n"] < 2:
                failures["n"] += 1
                raise RuntimeError("transient")
            return super().execute()

    db = PagingDB(8)
    assert len(db_paging.fetch_all(lambda: TwiceDown(db._rows, "t", db.log), retries=3)) == 8
    assert waits == [db_paging.RETRY_BACKOFF_SECONDS, 2 * db_paging.RETRY_BACKOFF_SECONDS]


def test_a_builder_that_sorts_but_cannot_page_is_read_once_in_the_stated_order():
    class SortsOnly:
        def __init__(self):
            self.terms, self.executed = [], 0

        def order(self, column, desc=False):
            self.terms.append((column, desc))
            return self

        def execute(self):
            self.executed += 1
            rows = [{"id": "2", "d": "b"}, {"id": "1", "d": "a"}]
            for column, desc in reversed(self.terms):
                rows.sort(key=lambda r: r[column], reverse=desc)
            return _Result(rows)

    q = SortsOnly()
    assert [r["id"] for r in db_paging.fetch_all_ordered(lambda: q, ("d",))] == ["1", "2"]
    assert q.executed == 1 and q.terms == [("d", False), ("id", False)]


def test_a_strict_read_raises_where_a_lenient_one_returns_part(small_pages):
    class Keyless(PagingQuery):
        def execute(self):
            self._log.append((self._name, 3, self._limit))
            return _Result([{"other": 1}] * 3)

    db = PagingDB()
    assert len(db_paging.fetch_all(lambda: Keyless(db._rows, "t", db.log))) == 3
    with pytest.raises(RuntimeError, match="nothing partial is returned"):
        db_paging.fetch_all(lambda: Keyless(db._rows, "t", db.log), strict=True)


def test_the_reporting_source_reads_strictly_and_orders_by_its_key_once():
    import ast
    import inspect
    from domain.reporting import sources
    src = inspect.getsource(sources.SupabaseLedgerSource)
    assert 'order("id")' not in src, "a reporting builder orders by id itself, and the pager orders by it again (id,id)"
    calls = [n for n in ast.walk(ast.parse(inspect.getsource(sources.SupabaseLedgerSource._fetch_all).lstrip()))
             if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "fetch_all"]
    assert calls and any(k.arg == "strict" and getattr(k.value, "value", None) is True for k in calls[0].keywords)
