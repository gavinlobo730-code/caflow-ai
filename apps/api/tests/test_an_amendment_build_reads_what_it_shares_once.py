"""POST-A-265 (the reads) — an amendment build reads once what every earlier period's rebuild would read again, and the answer is the same.

WHAT WAS WRONG
    The main GSTR-1 build rebuilds each earlier filed period from the books to look for amendments. Measured on a counting double over a
    seeded client with six filed months, three drifted, one build made 105 reads for three proposing periods: the client four times a
    period, the registrations three times, the invoices twice, the credit notes, the debit notes, their lines, their customers, the year's
    turnover, and, in the rebuild, the whole ledger of the month (every entry dated in it, then every line of each, in chunks), none of it
    changing from one period to the next. The periods already ran four at a time; this removes the repeated reads.

WHAT THIS HOLDS
    SAME ANSWER   the outstanding amendments are identical with the memo and without it, on a drifted year, on a year with a gap between two
                  filed months, and one at a time as well as four at a time. The cases are not vacuous (several periods propose amendments);
    READS         the whole build's reads are bounded by table (the client-wide reads once, the documents once for the span, one filed-return
                  read per period), and the ledger is not read at all by a rebuild, though the main build's own reconciliation still reads it;
    LEDGER        `gstr1_from_books(reconcile_to_ledger=False)` carries the same payload, gaps and totals as the default and `reconciliation`
                  None, and no consumer of `drift_since_filing` reads the reconciliation (a rule over the source, not a list);
    MEMO          a read is remembered only inside a scope, once even when several threads ask at the same moment, never when it failed, and
                  as a copy; a window answers a span by slicing on the date column exactly as the query's bounds would; ids already held
                  are not asked for again; with no scope open every reader reads every time, as it always did;
    SCOPE         the scope ends with the build, so nothing is remembered across requests.
"""
from __future__ import annotations

import ast
import collections
import contextlib
import contextvars
import pathlib
import threading

import pytest

import services.gst_amendment_service as svc
import services.gst_read_memo as memo
import services.gst_return_service as grs
import routers.gst_workspace as gw
from tests.e2e_harness import FakeDB, seed_standard_coa, wire_e2e
from tests.test_an_amendment_build_rebuilds_its_earlier_periods_several_at_a_time import (
    CLIENT, FIRM, GSTIN, _drifted_year, _file, _invoice,
)

API = pathlib.Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def _a_fresh_pool():
    """The rebuild pool is made on first use at the ceiling then in force; each test gets its own."""
    svc._REBUILD_POOL = None
    yield
    if svc._REBUILD_POOL is not None:
        svc._REBUILD_POOL.shutdown(wait=True)
    svc._REBUILD_POOL = None


@pytest.fixture
def db(monkeypatch):
    d = FakeDB()
    wire_e2e(monkeypatch, d, [gw, grs])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    d.seed("firms", {"id": FIRM, "name": "F", "locked_financial_years": []})
    d.seed("clients", {"id": CLIENT, "firm_id": FIRM, "gstin": GSTIN, "financial_year_start": "2025-04-01", "state_code": "27"})
    d.seed("customers", {"id": "CUST", "firm_id": FIRM, "client_id": CLIENT, "name": "Acme", "gstin": "27BBBBB1111B1ZN",
                         "state_code": "27", "is_active": True})
    seed_standard_coa(d, FIRM, CLIENT)
    return d


class _Counting:
    """Counts the `execute()` calls made through `db.table(...)`, by table, from every thread."""

    def __init__(self, database):
        self.counts: collections.Counter = collections.Counter()
        self._lock = threading.Lock()
        self._real = database.table
        database.table = self._table

    def _table(self, name):
        query = self._real(name)
        original = query.execute

        def execute(*a, **k):
            with self._lock:
                self.counts[name] += 1
            return original(*a, **k)

        query.execute = execute
        return query


@contextlib.contextmanager
def _no_memo(monkeypatch):
    """The build as it was: no scope is ever opened, so every reader reads every time."""
    monkeypatch.setattr(svc.gst_read_memo, "scope", lambda window=None: contextlib.nullcontext())
    monkeypatch.setattr(svc, "_prime_reads", lambda *a, **k: None)
    yield


# ── the answer is the same ───────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("parallel", [1, 4])
def test_the_outstanding_amendments_are_the_same_with_the_memo_and_without_it(db, monkeypatch, parallel):
    _drifted_year(db)
    monkeypatch.setattr(svc, "_MAX_PARALLEL_REBUILDS", parallel)
    with_memo = svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    with _no_memo(monkeypatch):
        without = svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    assert len(with_memo["source_periods"]) >= 3, "the case proposed nothing, so the comparison proves nothing"
    assert with_memo == without


def test_a_gap_between_two_filed_months_is_read_but_never_leaks_into_either(db, monkeypatch):
    """April and July are filed; May and June are not. The span read once covers the gap, and the slicing keeps each period to its own."""
    for m in (4, 5, 6, 7):
        _invoice(db, f"INV-{m:02d}", f"2025-{m:02d}-10", 1_00_000_00)
    _file(db, "042025")
    _file(db, "072025")
    for r in db.rows("client_sales_invoices"):                      # April and July drift; May and June (unfiled) carry documents too
        if r["invoice_no"] in ("INV-04", "INV-07"):
            r["taxable_amount_paise"] = 1_50_000_00
            r["cgst_paise"] = r["sgst_paise"] = 1_50_000_00 * 9 // 100
            r["total_paise"] = r["taxable_amount_paise"] + 2 * r["cgst_paise"]
    monkeypatch.setattr(svc, "_MAX_PARALLEL_REBUILDS", 1)
    with_memo = svc.outstanding_amendments(db, FIRM, CLIENT, "082025")
    with _no_memo(monkeypatch):
        without = svc.outstanding_amendments(db, FIRM, CLIENT, "082025")
    assert with_memo["source_periods"] == ["042025", "072025"], with_memo["source_periods"]
    assert with_memo == without


def test_a_cancelled_invoice_and_a_credit_note_are_sliced_to_their_own_period_too(db, monkeypatch):
    _drifted_year(db)
    db.seed("credit_notes", {"firm_id": FIRM, "client_id": CLIENT, "customer_id": "CUST", "credit_note_no": "CN-1",
                             "credit_note_date": "2025-07-15", "status": "issued", "taxable_amount_paise": 10_000_00,
                             "cgst_paise": 90_000, "sgst_paise": 90_000, "igst_paise": 0, "is_interstate": False,
                             "original_invoice_id": None})
    cancelled = _invoice(db, "INV-08-X", "2025-08-12", 40_000_00)
    cancelled["status"] = "cancelled"
    monkeypatch.setattr(svc, "_MAX_PARALLEL_REBUILDS", 1)
    with_memo = svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    with _no_memo(monkeypatch):
        without = svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    assert with_memo == without


# ── the reads ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_whole_build_reads_each_shared_thing_once_and_the_ledger_not_at_all(db, monkeypatch):
    _drifted_year(db)
    counting = _Counting(db)
    monkeypatch.setattr(svc, "_MAX_PARALLEL_REBUILDS", 1)
    svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    c = counting.counts
    total = sum(c.values())
    assert total <= 25, f"{total} reads for six earlier periods (it was 105): {dict(c)}"
    # The client-wide reads: a handful for the whole build, never a number that grows with the periods.
    assert c["clients"] <= 3 and c["client_gst_registrations"] <= 2 and c["client_gst_turnover"] <= 1, dict(c)
    # The documents of the span: once for the whole span (invoices and cancelled invoices are two reads), not once per period.
    assert c["client_sales_invoices"] <= 2 and c["credit_notes"] <= 1 and c["sales_debit_notes"] <= 1, dict(c)
    assert c["client_sales_invoice_lines"] <= 1 and c["customers"] <= 1, dict(c)
    # A rebuild reads no part of the ledger: that reconciliation belongs to the main build, not to the comparison.
    assert c["journal_entries"] == 0 and c["journal_lines"] == 0 and c["chart_of_accounts"] == 0, dict(c)
    # What does stay per period is the filed return it is compared with.
    assert c["gstr1_returns"] <= 6 + 4, dict(c)


def test_the_reads_do_not_grow_with_the_number_of_earlier_periods(db, monkeypatch):
    for m in range(4, 12):
        _invoice(db, f"INV-{m:02d}", f"2025-{m:02d}-10", 1_00_000_00)
        _file(db, f"{m:02d}2025")
    counting = _Counting(db)
    monkeypatch.setattr(svc, "_MAX_PARALLEL_REBUILDS", 1)
    svc.outstanding_amendments(db, FIRM, CLIENT, "122025")
    eight = sum(counting.counts.values())
    assert eight <= 8 * 2 + 14, f"{eight} reads for eight periods: the shared reads are being made per period again"


def test_the_main_build_still_reconciles_to_the_ledger(db):
    """The default is unchanged: only the comparison's rebuild leaves the reconciliation out."""
    _invoice(db, "INV-04", "2025-04-10", 1_00_000_00)
    built = grs.gstr1_from_books(db, FIRM, CLIENT, "042025", GSTIN)
    assert built["reconciliation"] is not None and "net_output_gst" in built["reconciliation"]


# ── the ledger reconciliation is not part of the comparison ──────────────────────────────────────────────────────────────

def test_a_rebuild_without_the_reconciliation_carries_everything_else_the_same(db):
    _invoice(db, "INV-04", "2025-04-10", 1_00_000_00)
    full = grs.gstr1_from_books(db, FIRM, CLIENT, "042025", GSTIN)
    counting = _Counting(db)
    lean = grs.gstr1_from_books(db, FIRM, CLIENT, "042025", GSTIN, reconcile_to_ledger=False)
    assert lean["reconciliation"] is None
    assert {k: v for k, v in lean.items() if k != "reconciliation"} == {k: v for k, v in full.items() if k != "reconciliation"}
    assert counting.counts["journal_entries"] == 0 and counting.counts["journal_lines"] == 0 and counting.counts["chart_of_accounts"] == 0


def test_the_drift_rebuild_asks_for_no_reconciliation(db, monkeypatch):
    import services.gst_exception_service as ex
    seen = {}
    real = grs.gstr1_from_books

    def spy(*a, **k):
        seen.update(k)
        return real(*a, **k)

    monkeypatch.setattr(grs, "gstr1_from_books", spy)
    _invoice(db, "INV-04", "2025-04-10", 1_00_000_00)
    ex.drift_since_filing(db, FIRM, CLIENT, "042025", GSTIN, {})
    assert seen.get("reconcile_to_ledger") is False


def test_no_consumer_of_the_drift_rebuild_reads_its_ledger_reconciliation():
    """The rule the saving rests on, over the source: a module that calls `drift_since_filing` never subscripts or `.get`s "reconciliation".
    Were one to start, it would read None."""
    offenders = []
    for path in sorted((API / "services").glob("*.py")) + sorted((API / "routers").glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        calls_drift = any(isinstance(n, ast.Call) and getattr(n.func, "attr", getattr(n.func, "id", None)) == "drift_since_filing"
                          for n in ast.walk(tree))
        if not calls_drift or path.name == "gst_exception_service.py":
            continue
        for n in ast.walk(tree):
            text = ast.unparse(n) if isinstance(n, (ast.Subscript, ast.Call)) else ""
            if "'reconciliation'" in text or '"reconciliation"' in text:
                offenders.append(f"{path.name}:{getattr(n, 'lineno', '?')}")
    assert not offenders, offenders


# ── the memo itself ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_thread_started_without_the_callers_context_sees_no_scope_and_reads_for_itself():
    """The safe direction: a scope reaches a thread only through the context copy the build's pool makes; any other thread simply reads."""
    seen = []
    with memo.scope():
        memo.remember("k", lambda: 1)
        t = threading.Thread(target=lambda: seen.append(memo.active()))
        t.start()
        t.join(timeout=5)
    assert seen == [None]


def test_with_no_scope_every_read_reads_every_time():
    calls = []
    assert memo.active() is None
    for _ in range(3):
        memo.remember("k", lambda: calls.append(1) or {"a": 1})
    assert len(calls) == 3
    rows = [{"d": "2025-04-10"}]
    for _ in range(2):
        memo.window_rows("t", "f", "c", "2025-04-01", "2025-04-30", "d", lambda a, b: calls.append((a, b)) or rows)
    assert calls[-2:] == [("2025-04-01", "2025-04-30")] * 2


def test_a_read_is_remembered_inside_a_scope_once_and_handed_out_as_a_copy():
    calls = []
    with memo.scope():
        first = memo.remember("k", lambda: calls.append(1) or {"nested": [1, 2]})
        first["nested"].append(3)                                  # a caller that annotates what it was handed
        second = memo.remember("k", lambda: calls.append(1) or {"nested": [9]})
    assert calls == [1] and second == {"nested": [1, 2]}, (calls, second)
    assert memo.active() is None, "the scope ended with the build"


def test_several_threads_asking_at_once_load_once():
    calls, release, started = [], threading.Event(), threading.Event()

    def loader():
        calls.append(1)
        started.set()
        release.wait(timeout=5)
        return 7

    results = []
    with memo.scope():
        def ask():
            results.append(memo.remember("k", loader))

        # as the build's pool does: each task runs in a copy of the caller's context, which is how the scope reaches the thread
        threads = [threading.Thread(target=contextvars.copy_context().run, args=(ask,)) for _ in range(6)]
        for t in threads:
            t.start()
        assert started.wait(timeout=5)
        release.set()
        for t in threads:
            t.join(timeout=5)
    assert calls == [1] and results == [7] * 6


def test_a_loader_that_raises_is_not_remembered_and_the_next_asker_loads_again():
    state = {"n": 0}

    def flaky():
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("the read failed")
        return "ok"

    with memo.scope():
        with pytest.raises(RuntimeError):
            memo.remember("k", flaky)
        assert memo.remember("k", flaky) == "ok"
    assert state["n"] == 2


def test_a_window_answers_a_span_by_slicing_on_the_date_exactly_as_the_query_bounds_would():
    rows = [{"id": "a", "d": "2025-03-31"}, {"id": "b", "d": "2025-04-01"}, {"id": "c", "d": "2025-04-30"},
            {"id": "d", "d": "2025-05-01"}, {"id": "e", "d": None}, {"id": "f", "d": "2025-06-15"}]
    loads = []

    def loader(a, b):
        loads.append((a, b))
        return [r for r in rows if r["d"] is not None and a <= r["d"] <= b]      # what gte/lte on a DATE column answer

    with memo.scope(window=("2025-03-01", "2025-06-30")):
        april = memo.window_rows("t", "f", "c", "2025-04-01", "2025-04-30", "d", loader)
        may = memo.window_rows("t", "f", "c", "2025-05-01", "2025-05-31", "d", loader)
        outside = memo.window_rows("t", "f", "c", "2025-07-01", "2025-07-31", "d", loader)
    assert [r["id"] for r in april] == ["b", "c"] and [r["id"] for r in may] == ["d"]
    assert loads == [("2025-03-01", "2025-06-30"), ("2025-07-01", "2025-07-31")], "the window once, the outsider as asked"
    assert outside == []


def test_a_window_hands_out_copies_of_its_rows():
    with memo.scope(window=("2025-04-01", "2025-04-30")):
        first = memo.window_rows("t", "f", "c", "2025-04-01", "2025-04-30", "d", lambda a, b: [{"d": "2025-04-02", "x": 1}])
        first[0]["x"] = 99
        again = memo.window_rows("t", "f", "c", "2025-04-01", "2025-04-30", "d", lambda a, b: [{"d": "2025-04-02", "x": 1}])
    assert again[0]["x"] == 1


def test_ids_already_held_are_not_asked_for_again_and_an_absent_id_is_remembered_as_absent():
    asked = []

    def loader(ids):
        asked.append(list(ids))
        return [{"id": i, "name": i.upper()} for i in ids if i != "gone"]

    with memo.scope():
        one = memo.rows_by_id("customers", "f", ["a", "b"], loader)
        two = memo.rows_by_id("customers", "f", ["b", "c", "gone"], loader)
        three = memo.rows_by_id("customers", "f", ["gone", "a"], loader)
    assert asked == [["a", "b"], ["c", "gone"]], asked
    assert [r["id"] for r in one] == ["a", "b"] and [r["id"] for r in two] == ["b", "c"] and [r["id"] for r in three] == ["a"]


def test_rows_by_id_groups_a_documents_lines_under_its_foreign_key():
    def loader(ids):
        return [{"sales_invoice_id": "i1", "n": 1}, {"sales_invoice_id": "i1", "n": 2}, {"sales_invoice_id": "i2", "n": 3}]

    with memo.scope():
        rows = memo.rows_by_id("client_sales_invoice_lines", "", ["i1", "i2"], loader, id_field="sales_invoice_id")
    assert [r["n"] for r in rows] == [1, 2, 3]


# ── the scope ends with the build ────────────────────────────────────────────────────────────────────────────────────────

def test_the_scope_is_closed_when_the_build_returns_and_when_it_fails(db, monkeypatch):
    _drifted_year(db)
    svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    assert memo.active() is None
    monkeypatch.setattr(svc, "gstr1_exceptions", lambda *a: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    assert memo.active() is None


def test_a_failed_priming_costs_only_the_saving(db, monkeypatch):
    _drifted_year(db)
    monkeypatch.setattr(svc, "_MAX_PARALLEL_REBUILDS", 1)
    expected = svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    monkeypatch.setattr(grs, "_classified_sales_documents", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("prime failed")))
    # the rebuilds themselves call the same function, so a failure there is the build's own and is raised as it always was
    with pytest.raises(RuntimeError):
        svc.outstanding_amendments(db, FIRM, CLIENT, "102025")
    assert expected["source_periods"]
