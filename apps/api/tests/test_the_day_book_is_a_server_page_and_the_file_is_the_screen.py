"""The Day Book is a page the server cuts, and the PDF and Excel files are the screen (POST-A-091).

WHAT WAS WRONG
    The Day Book screen read `journal_entries` straight over PostgREST with every entry's lines embedded, for the whole
    period, and summed a debit column out of them in the browser. No server function existed, so the one book an auditor
    asks for first had no printable form, and a second reader inside an export is how a file and a screen come to disagree.

WHAT THIS HOLDS (the database side is `test_day_book_sql_parity_pg.py`)
    1. THE BUILDER: the window is inclusive at both ends, the order is chronological and reverses whole for newest first, a
       page is a slice and the footer is the window's, the documents are counted in byte order with none last.
    2. THE SERVICE: with a database the page is cut by `day_book_page` and a failure is RAISED (the ledger falls back to a
       Python builder that costs one account; a Day Book fallback would read the client's whole period silently); without
       one the builder answers; a missing bound is the financial year and today.
    3. THE FILE IS THE SCREEN: the export reads the pages the screen reads, through the same service function, to the last
       entry, and a document that does not foot is REFUSED rather than printed: a short read, an entry out of balance, debits
       that differ from credits, a period past the ceiling (refused after ONE page, before it is read whole).
    4. THE DOOR: scope, permission, strict dates, a limit the server clamps, `has_more` from the server's own count and a
       failed read said in words and never an empty book.
"""
from __future__ import annotations

import ast
import inspect
import io
import re
from pathlib import Path

import pytest

from domain.reporting import (
    Account, InMemoryLedgerSource, JournalEntry, JournalLine, ReportingService,
)
from domain.reporting import builders
from domain.reporting import export_builders as B
from domain.reporting.export_document import ExportRefused
from services import report_export_service as ex

API = Path(__file__).resolve().parents[1]
FIRM, CLIENT = "firm-db", "client-db"
START, END = "2026-04-01", "2027-03-31"

ACCOUNTS = [
    Account("ar", "1100", "Trade Receivables", "Asset", "Receivable", system_key="ar"),
    Account("rev", "4000", "Sales", "Revenue"),
]


def je(jid, date, amount=1000, *, source_type=None, source_id=None, created_at=None,
       ref="auto", narration="auto", lines=None, client=CLIENT):
    built = lines if lines is not None else [("ar", amount, 0), ("rev", 0, amount)]
    return JournalEntry(
        id=jid, entry_date=date, client_id=client, firm_id=FIRM, entry_type="Journal",
        lines=tuple(JournalLine(*ln) for ln in built),
        reference_no=f"R-{jid}" if ref == "auto" else ref,
        narration=f"Sale {jid}" if narration == "auto" else narration,
        created_at=created_at or f"{date}T00:00:00",
        source_type=source_type, source_id=source_id)


def by_id(entries):
    return {e.id: e for e in entries}


def book_of(entries):
    return ReportingService(InMemoryLedgerSource(accounts=ACCOUNTS, entries=list(entries)))


# ── 1. the builder ───────────────────────────────────────────────────────────

def test_both_ends_of_the_window_are_inclusive_and_outside_is_out():
    es = [je("before", "2026-03-31"), je("first", START), je("mid", "2026-09-01"),
          je("last", END), je("after", "2027-04-01")]
    got = builders.day_book(by_id(es), START, END, limit=100)
    assert [e["entry_id"] for e in got["entries"]] == ["first", "mid", "last"]
    assert got["total_entries"] == 3


def test_the_order_is_date_then_recorded_then_id_and_reverses_whole():
    es = [je("b", "2026-06-01", created_at="2026-06-01T10:00:00"),
          je("a", "2026-06-01", created_at="2026-06-01T10:00:00"),
          je("late", "2026-06-01", created_at="2026-06-01T11:00:00"),
          je("early", "2026-05-01")]
    asc = [e["entry_id"] for e in builders.day_book(by_id(es), START, END, limit=100)["entries"]]
    assert asc == ["early", "a", "b", "late"]
    desc = [e["entry_id"] for e in builders.day_book(by_id(es), START, END, newest_first=True,
                                                     limit=100)["entries"]]
    assert desc == list(reversed(asc))


def test_an_entry_carries_its_own_debit_and_credit_totals():
    e = je("m", "2026-06-01", lines=[("ar", 700, 0), ("ar", 300, 0), ("rev", 0, 400), ("rev", 0, 600)])
    row = builders.day_book(by_id([e]), START, END, limit=10)["entries"][0]
    assert (row["debit_paise"], row["credit_paise"]) == (1000, 1000)
    assert "lines" not in row, "the lines are summed in the database and never cross the wire"


def test_a_page_is_a_slice_and_the_footer_is_the_windows():
    es = [je(f"e{i:02d}", f"2026-06-{(i % 27) + 1:02d}", 100 + i) for i in range(30)]
    whole = builders.day_book(by_id(es), START, END, limit=1000)
    page = builders.day_book(by_id(es), START, END, limit=10, offset=20)
    assert [e["entry_id"] for e in page["entries"]] == [e["entry_id"] for e in whole["entries"][20:30]]
    for key in ("total_entries", "total_debit_paise", "total_credit_paise", "sources"):
        assert page[key] == whole[key], f"{key} must describe the window and not the page"
    assert page["limit"] == 10 and page["offset"] == 20
    assert builders.day_book(by_id(es), START, END, limit=10, offset=999)["entries"] == []


def test_the_limit_and_the_offset_are_clamped_like_the_function_does():
    es = [je("a", "2026-06-01")]
    assert builders.day_book(by_id(es), START, END, limit=0)["limit"] == 1
    assert builders.day_book(by_id(es), START, END, limit=99999)["limit"] == builders.DAY_BOOK_MAX_PAGE == 1000
    assert builders.day_book(by_id(es), START, END, limit=5, offset=-4)["offset"] == 0


def test_the_documents_are_counted_in_byte_order_with_none_last():
    es = [je("1", "2026-05-01", source_type="manual"), je("2", "2026-05-02", source_type="Opening"),
          je("3", "2026-05-03", source_type="sales_invoice"), je("4", "2026-05-04"),
          je("5", "2026-05-05", source_type="sales_invoice"), je("6", "2026-05-06", source_type="TrialBalance")]
    sources = builders.day_book(by_id(es), START, END, limit=100)["sources"]
    assert sources == [
        {"source_type": "Opening", "entries": 1}, {"source_type": "TrialBalance", "entries": 1},
        {"source_type": "manual", "entries": 1}, {"source_type": "sales_invoice", "entries": 2},
        {"source_type": None, "entries": 1}]


def test_an_entry_with_no_source_keeps_both_keys_as_null():
    row = builders.day_book(by_id([je("n", "2026-06-01")]), START, END, limit=10)["entries"][0]
    assert row["source_type"] is None and row["source_id"] is None
    assert "source_type" in row and "source_id" in row


def test_an_empty_window_is_a_real_answer_with_a_zero_footer():
    got = builders.day_book({}, START, END, limit=10)
    assert got["entries"] == [] and got["total_entries"] == 0
    assert got["total_debit_paise"] == got["total_credit_paise"] == 0 and got["sources"] == []


# ── 2. the service ───────────────────────────────────────────────────────────

class _Rpc:
    def __init__(self, data=None, boom=None):
        self.data, self.boom, self.calls = data, boom, []

    def rpc(self, name, args):
        self.calls.append((name, args))
        outer = self

        class _Exec:
            def execute(self_inner):
                if outer.boom:
                    raise outer.boom
                return type("R", (), {"data": outer.data})()
        return _Exec()


class _DbSource(InMemoryLedgerSource):
    """An in-memory source that looks like it has a database."""

    def __init__(self, db, **kw):
        super().__init__(**kw)
        self.db = db


def _svc_with(db):
    return ReportingService(_DbSource(db, accounts=ACCOUNTS, entries=[]))


def test_with_a_database_the_page_is_cut_by_the_function_with_the_callers_arguments():
    page = {"entries": [], "total_entries": 0, "total_debit_paise": 0, "total_credit_paise": 0, "sources": []}
    db = _Rpc(page)
    out = _svc_with(db).day_book(FIRM, CLIENT, START, END, newest_first=True, limit=500, offset=40)
    assert out is page
    assert db.calls == [("day_book_page", {
        "p_firm": FIRM, "p_client": CLIENT, "p_start": START, "p_end": END,
        "p_newest_first": True, "p_limit": 500, "p_offset": 40})]


def test_a_failure_with_a_database_is_raised_and_never_answered_from_a_whole_read():
    with pytest.raises(RuntimeError, match="boom"):
        _svc_with(_Rpc(boom=RuntimeError("boom"))).day_book(FIRM, CLIENT, START, END, limit=10)
    with pytest.raises(ValueError, match="not a Day Book page"):
        _svc_with(_Rpc(data=[])).day_book(FIRM, CLIENT, START, END, limit=10)


def test_a_database_is_never_asked_for_the_whole_period_at_once():
    with pytest.raises(ValueError, match="a page at a time"):
        _svc_with(_Rpc({})).day_book(FIRM, CLIENT, START, END)


def test_the_service_has_no_whole_read_fallback_after_a_failure():
    """THE RULE, NOT A NAME: the Python builder is reachable only on the branch that has no database."""
    fn = ast.parse(inspect.getsource(ReportingService.day_book).strip()).body[0]
    builder_calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
                     and isinstance(n.func, ast.Attribute) and n.func.attr == "day_book"
                     and isinstance(n.func.value, ast.Name) and n.func.value.id == "builders"]
    assert len(builder_calls) == 1
    first_if = next(n for n in fn.body if isinstance(n, ast.If))
    assert any(builder_calls[0] in ast.walk(stmt) for stmt in first_if.body), \
        "builders.day_book must sit inside the `if db is None` branch"
    handlers = [h for n in ast.walk(fn) if isinstance(n, ast.Try) for h in n.handlers]
    assert handlers and all(any(isinstance(s, ast.Raise) for s in ast.walk(h)) for h in handlers), \
        "every handler re-raises: a failure is not answered from a read of the whole period"


def test_a_missing_bound_is_the_financial_year_and_today():
    from core.ist_clock import ist_today
    got = book_of([je("a", "2026-06-01")]).day_book(FIRM, CLIENT, None, None, limit=10)
    assert got["end_date"] == ist_today().isoformat() and got["start_date"] <= got["end_date"]


# ── 3. the file is the screen ────────────────────────────────────────────────

class PagedBook:
    """Behaves like `ReportingService.day_book` over `n` entries: every page carries the window's footer."""

    def __init__(self, n, *, short_after=None, skew_credit=0, entry_skew=None):
        self.n, self.short_after, self.calls = n, short_after, []
        self.entries = []
        for i in range(n):
            amount = 100 + i
            self.entries.append({
                "entry_id": f"e{i}", "entry_date": "2026-06-01", "reference_no": f"R{i}", "narration": f"n{i}",
                "entry_type": "Journal", "source_type": "sales_invoice" if i % 2 else None,
                "source_id": None, "debit_paise": amount, "credit_paise": amount})
        if entry_skew is not None:
            self.entries[entry_skew]["credit_paise"] += 1
        self.total = sum(e["debit_paise"] for e in self.entries)
        self.credit_total = sum(e["credit_paise"] for e in self.entries) + skew_credit

    def day_book(self, firm_id, client_id, start, end, *, newest_first=False, limit=None, offset=0):
        self.calls.append((newest_first, limit, offset))
        page = self.entries[offset: offset + limit]
        if self.short_after is not None and offset >= self.short_after:
            page = []
        return {"start_date": start, "end_date": end, "entries": page, "total_entries": self.n,
                "total_debit_paise": self.total, "total_credit_paise": self.credit_total,
                "sources": [], "newest_first": newest_first, "limit": limit, "offset": offset}


def test_a_book_longer_than_one_page_is_read_to_its_last_entry_in_date_order():
    stub = PagedBook(2350)
    book = ex.fetch_day_book(stub, FIRM, CLIENT, START, END, ceiling=10_000)
    assert len(book["entries"]) == 2350
    assert stub.calls == [(False, 1000, 0), (False, 1000, 1000), (False, 1000, 2000)]
    doc = B.day_book_document(book)                       # foots, so it is not refused
    assert len(doc.tables[0].rows) == 2350 + 1            # every entry and the total


def test_a_read_that_comes_back_short_is_a_refusal_not_a_short_book():
    book = ex.fetch_day_book(PagedBook(2350, short_after=1000), FIRM, CLIENT, START, END, ceiling=10_000)
    assert len(book["entries"]) == 1000
    with pytest.raises(ExportRefused, match="not printed"):
        B.day_book_document(book)


def test_a_book_over_the_ceiling_is_refused_in_words_after_one_page():
    stub = PagedBook(3000)
    with pytest.raises(ExportRefused, match=r"3,000 entries.*limited to 2,000"):
        ex.fetch_day_book(stub, FIRM, CLIENT, START, END, ceiling=2_000)
    assert stub.calls == [(False, 1000, 0)], "refused after ONE page, not after reading them all"


def test_debits_that_differ_from_credits_are_not_printed():
    book = ex.fetch_day_book(PagedBook(3, skew_credit=0, entry_skew=1), FIRM, CLIENT, START, END, ceiling=100)
    with pytest.raises(ExportRefused, match="debits and credits differ"):
        B.day_book_document(book)


def test_an_entry_out_of_balance_is_named_and_not_printed():
    """Two entries each one paisa out the other way: the window's totals agree and the count is right, so only the entry
    itself is wrong, and it is named."""
    book = {"start_date": START, "end_date": END, "total_entries": 2,
            "total_debit_paise": 201, "total_credit_paise": 201, "sources": [],
            "entries": [
                {"entry_id": "e0", "entry_date": "2026-06-01", "reference_no": "R0", "narration": "a",
                 "entry_type": "Journal", "source_type": None, "source_id": None,
                 "debit_paise": 100, "credit_paise": 101},
                {"entry_id": "e1", "entry_date": "2026-06-02", "reference_no": "R1", "narration": "b",
                 "entry_type": "Journal", "source_type": None, "source_id": None,
                 "debit_paise": 101, "credit_paise": 100}]}
    with pytest.raises(ExportRefused, match=r"2 entries are out of balance, the first being R0 dated 2026-06-01"):
        B.day_book_document(book)


def test_the_document_is_the_pages_figures_with_one_amount_per_entry():
    book = ex.fetch_day_book(PagedBook(4), FIRM, CLIENT, START, END, ceiling=100)
    doc = B.day_book_document(book)
    rows = doc.tables[0].rows
    assert [r.cells[5] for r in rows[:-1]] == [100, 101, 102, 103]
    assert rows[-1].cells[5] == 100 + 101 + 102 + 103 == book["total_debit_paise"]
    assert rows[-1].style == "emphasis" and "4 entries" in rows[-1].cells[2]
    assert doc.report_id == "day-book" and doc.period == f"{START} to {END}"
    # The origin is a capitalised name where there is one and an EMPTY cell where there is none.
    assert [r.cells[4] for r in rows[:-1]] == ["", "Sales invoice", "", "Sales invoice"]
    assert any("Posted entries only" in n for n in doc.notes)


def test_the_export_offers_a_pdf_and_a_spreadsheet_and_both_carry_the_total():
    pdfplumber = pytest.importorskip("pdfplumber")
    es = [je("a", "2026-06-01", 123_456_750), je("b", "2026-06-02", 29, source_type="sales_invoice")]
    svc = book_of(es)

    class _Q:
        def __init__(self, data): self._d = data
        def select(self, *a, **k): return self
        def eq(self, *a, **k): return self
        def limit(self, *a, **k): return self
        def maybe_single(self): return self
        def execute(self): return type("R", (), {"data": self._d})()

    class _Db:
        def table(self, name):
            return _Q([{"id": FIRM, "name": "Sharma & Co.", "gstin": None, "gst_number": "27AABCS1429B1ZU"}]
                      if name == "firms" else
                      {"id": CLIENT, "client_name": "Acme", "legal_name": "Acme Traders Pvt Ltd",
                       "gstin": "27AAACA1111A1Z4", "pan": "AAACA1111A"})

    out = ex.export_report("day-book", "pdf", svc=svc, db=_Db(), firm_id=FIRM, client_id=CLIENT,
                           params={"start_date": START, "end_date": END}, generated_on="2026-10-01")
    with pdfplumber.open(io.BytesIO(out.content)) as doc:
        text = "\n".join((p.extract_text() or "") for p in doc.pages)
    assert "Day Book" in text and "12,34,567.79" in text and "Total for the period (2 entries)" in text
    assert out.filename.startswith("day-book-") and out.media_type == "application/pdf"
    xl = ex.export_report("day-book", "xlsx", svc=svc, db=_Db(), firm_id=FIRM, client_id=CLIENT,
                          params={"start_date": START, "end_date": END}, generated_on="2026-10-01")
    assert xl.content[:2] == b"PK" and xl.filename.endswith(".xlsx")


def test_the_day_book_is_offered_in_both_formats_and_no_other_is_invented():
    assert ex.REPORTS[B.DAY_BOOK] == (ex.PDF, ex.XLSX)
    assert ex.MAX_DAY_BOOK_ENTRIES_PDF == 6_000 and ex.MAX_DAY_BOOK_ENTRIES_XLSX == 50_000


def test_the_fetcher_reads_the_service_and_no_table_itself():
    src = inspect.getsource(ex.fetch_day_book)
    assert "svc.day_book(" in src and ".table(" not in src and "journal_" not in src


# ── 4. the door ──────────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException            # noqa: E402
from fastapi.testclient import TestClient              # noqa: E402

import routers.accounting as door                      # noqa: E402
from core.auth import get_current_user                 # noqa: E402

PARTNER = {"id": "u1", "firm_id": FIRM, "role": "Partner", "email": "p@f.test", "auth_user_id": "auth-1"}
REVIEWER = {**PARTNER, "id": "u2", "role": "Reviewer"}


def _http(monkeypatch, user=PARTNER, *, service=None):
    app = FastAPI()
    app.include_router(door.router)
    app.dependency_overrides[get_current_user] = lambda: user
    if service is not None:
        monkeypatch.setattr(door, "_reporting_service", lambda current_user=None: service)
    return TestClient(app, raise_server_exceptions=False)


class _Svc:
    def __init__(self, page=None, boom=None):
        self.page, self.boom, self.calls = page, boom, []

    def day_book(self, firm_id, client_id, start, end, **kw):
        self.calls.append(dict(firm_id=firm_id, client_id=client_id, start=start, end=end, **kw))
        if self.boom:
            raise self.boom
        return self.page


def _page(n, total, offset=0, limit=500):
    return {"start_date": START, "end_date": END, "entries": [{"entry_id": f"e{i}"} for i in range(n)],
            "total_entries": total, "total_debit_paise": 0, "total_credit_paise": 0, "sources": [],
            "newest_first": True, "limit": limit, "offset": offset}


def test_the_page_says_whether_more_exist_from_the_servers_own_count(monkeypatch):
    svc = _Svc(_page(500, 1200))
    r = _http(monkeypatch, service=svc).get("/api/accounting/day-book", params={"client_id": CLIENT})
    body = r.json()
    assert r.status_code == 200 and body["success"] is True
    assert body["data"]["has_more"] is True and body["data"]["returned"] == 500
    assert body["data"]["max_limit"] == 1000
    # The caller's firm, the default window and newest first.
    assert svc.calls[0]["firm_id"] == FIRM and svc.calls[0]["newest_first"] is True
    assert svc.calls[0]["limit"] == 500 and svc.calls[0]["offset"] == 0


def test_the_last_page_says_there_is_no_more(monkeypatch):
    r = _http(monkeypatch, service=_Svc(_page(200, 1200, offset=1000))).get(
        "/api/accounting/day-book", params={"client_id": CLIENT, "offset": 1000})
    assert r.json()["data"]["has_more"] is False
    r = _http(monkeypatch, service=_Svc(_page(0, 0))).get("/api/accounting/day-book", params={"client_id": CLIENT})
    assert r.json()["data"]["has_more"] is False and r.json()["data"]["returned"] == 0


def test_a_failed_read_is_said_in_words_and_is_never_an_empty_book(monkeypatch):
    r = _http(monkeypatch, service=_Svc(boom=RuntimeError("db down"))).get(
        "/api/accounting/day-book", params={"client_id": CLIENT})
    body = r.json()
    assert body["success"] is False and body["data"] is None
    assert "could not be read" in body["error"] and "db down" not in body["error"]


def test_a_client_is_required_a_date_must_be_a_date_and_the_limit_is_bounded(monkeypatch):
    http = _http(monkeypatch, service=_Svc(_page(0, 0)))
    assert http.get("/api/accounting/day-book").status_code == 422
    assert http.get("/api/accounting/day-book", params={"client_id": CLIENT, "start_date": "01/04/2026"}).status_code == 422
    assert http.get("/api/accounting/day-book", params={"client_id": CLIENT, "limit": 1001}).status_code == 422
    assert http.get("/api/accounting/day-book", params={"client_id": CLIENT, "limit": 0}).status_code == 422
    assert http.get("/api/accounting/day-book", params={"client_id": CLIENT, "offset": -1}).status_code == 422


@pytest.mark.parametrize("param", ["start_date", "end_date"])
@pytest.mark.parametrize("day", ["2026-02-30", "2026-13-45", "2026-00-10", "2027-02-29", "2026-04-31"])
def test_a_day_that_is_not_on_the_calendar_is_a_422_in_words_and_reads_nothing(monkeypatch, param, day):
    """The query pattern admits any four-two-two digits; `2026-02-30` used to reach the database's date cast and come back as
    'could not be read, please try again', advice that cannot help."""
    svc = _Svc(_page(0, 0))
    r = _http(monkeypatch, service=svc).get("/api/accounting/day-book", params={"client_id": CLIENT, param: day})
    assert r.status_code == 422 and svc.calls == []
    assert param in r.json()["detail"] and "not a real date" in r.json()["detail"]


def test_the_day_check_reads_only_a_calendar_day_written_with_dashes():
    from core.validators import real_day_problem
    assert real_day_problem(None, "d") is None and real_day_problem("2028-02-29", "d") is None
    for bad in ("2026-02-30", "20260230", "2026-W09-1", "2026-2-3", "", " 2026-02-03", "2026-02-03T00:00", "\u0662\u0660\u0662\u0666-02-03"):
        assert real_day_problem(bad, "d") and "not a real date" in real_day_problem(bad, "d"), bad


def test_a_leap_day_is_a_day(monkeypatch):
    svc = _Svc(_page(0, 0))
    r = _http(monkeypatch, service=svc).get("/api/accounting/day-book", params={"client_id": CLIENT, "end_date": "2028-02-29"})
    assert r.status_code == 200 and svc.calls[0]["end"] == "2028-02-29"


def test_a_client_outside_the_callers_scope_is_refused_before_anything_is_read(monkeypatch):
    def deny(user, client_id):
        raise HTTPException(status_code=404, detail="Not found")

    svc = _Svc(_page(0, 0))
    monkeypatch.setattr(door, "assert_client_access", deny)
    r = _http(monkeypatch, service=svc).get("/api/accounting/day-book", params={"client_id": "theirs"})
    assert r.status_code == 404 and svc.calls == []


def test_a_role_without_accounting_read_cannot_open_the_day_book(monkeypatch):
    r = _http(monkeypatch, REVIEWER, service=_Svc(_page(0, 0))).get(
        "/api/accounting/day-book", params={"client_id": CLIENT})
    assert r.status_code == 403


def test_the_router_serves_the_ceiling_the_function_clamps_to():
    assert door.DAY_BOOK_MAX_LIMIT == builders.DAY_BOOK_MAX_PAGE == ex.DAY_BOOK_PAGE
    assert "LEAST(GREATEST(COALESCE(p_limit, 100), 1), 1000)" in _migration()


def _migration() -> str:
    return next(p for p in (API / "migrations").glob("517_the_day_book_is_a_page_*.sql")
                if not p.name.endswith("_rollback.sql")).read_text(encoding="utf-8")


def test_the_migration_is_read_only_runs_as_its_caller_and_sorts_bytes():
    code = re.sub(r"--[^\n]*", "", _migration())
    assert "SECURITY INVOKER" in code and "SECURITY DEFINER" not in code
    assert not re.search(r"\b(INSERT|UPDATE|DELETE|TRUNCATE|ALTER|DROP)\b", code), "a read-only function"
    assert 'COLLATE "C"' in code and "is_posted" in code and "deleted_at IS NULL" in code
    assert "FROM PUBLIC" in code and "FROM anon" in code and "TO authenticated, service_role" in code
