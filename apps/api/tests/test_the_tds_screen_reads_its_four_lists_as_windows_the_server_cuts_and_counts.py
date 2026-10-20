"""The TDS screen's four lists are windows the server orders, cuts and counts, and the figures over them are the server's (POST-A-276).

WHAT WAS WRONG
    `app/tds/page.tsx` read `tds_deductions`, `tds_challans`, `tds_returns` and `tds_certificates` itself over PostgREST, where `rbac()`
    and the caller's client assignment never run, and then worked out the footer under the deductions table, the "Returns Due" and
    "Certificates Pending" cards and the Returns tab's Overdue count in the browser, over whatever it had paged in. The four endpoints
    in `routers/tds_workspace` existed beside it and nothing called them: a bare array, in no stated order, with no word on whether
    more rows existed.

WHAT IS HELD
    * each endpoint answers a WINDOW in a stated total order (the day, latest first, then the id), so two requests never repeat or skip
      a row, with the server's `has_more`, `limit` and `max_limit`;
    * the footer's totals, the returns' Not filed / Filed / Overdue and the certificates' pending count are taken over ALL of the
      client's rows and not over the window;
    * Overdue is a return not filed whose due date has passed on the INDIAN day, a due date of today is not overdue, and a return with no
      due date is not called overdue;
    * another client's and another firm's rows are in none of it;
    * the sections the Add Challan form offers, and the names of every section, are the server's, and every section the registry holds
      has a name, so a section added to the registry without one fails here and not on a screen.
"""
from __future__ import annotations

from datetime import date

import pytest

import routers.tds_workspace as tw
from domain.tds import screen_counts
from domain.tds.section_labels import SECTION_LABELS, challan_sections, label_of
from domain.tds.section_rates import TDS_RATES_BY_FY, parent_of
from services import tds_register_lists_service as lists
from tests.e2e_harness import FakeDB

FIRM, CLIENT = "FIRM-A", "CLIENT-1"
CALLER = {"firm_id": FIRM, "id": "u", "auth_user_id": "auth", "email": "ca@f.test", "role": "Partner"}
TODAY = date(2026, 10, 20)


# ── the pure figures ────────────────────────────────────────────────────────

def test_the_totals_are_over_every_row_given_and_add_the_two_columns_as_stored():
    rows = [{"payment_amount_paise": 100_00, "tds_paise": 10_00}, {"payment_amount_paise": 50_00, "tds_paise": 5_00},
            {"payment_amount_paise": None, "tds_paise": "bad"}]
    assert screen_counts.deduction_totals(rows) == {"count": 3, "payment_amount_paise": 150_00, "tds_paise": 15_00}
    assert screen_counts.deduction_totals([]) == {"count": 0, "payment_amount_paise": 0, "tds_paise": 0}


@pytest.mark.parametrize("status, filed", [("filed", True), ("revised", True), ("FILED", True), ("pending", False),
                                            ("prepared", False), ("ca_approved", False), (None, False), ("", False)])
def test_a_return_is_filed_once_it_is_filed_or_revised(status, filed):
    assert screen_counts.is_filed(status) is filed


@pytest.mark.parametrize("due, status, overdue", [
    ("2026-10-19", "pending", True),         # yesterday
    ("2026-10-20", "pending", False),        # due today is not yet late
    ("2026-10-21", "pending", False),
    ("2026-10-19", "filed", False),          # filed on time or late, it is not overdue now
    ("2026-10-19", "revised", False),
    (None, "pending", False),                # an absent date is unknown, not a date in the past
    ("", "pending", False),
    ("2026-10-19T23:30:00+00:00", "prepared", True),
])
def test_a_return_is_overdue_when_it_is_not_filed_and_its_due_date_has_passed(due, status, overdue):
    assert screen_counts.is_overdue({"due_date": due, "status": status}, TODAY) is overdue


def test_the_return_counts_make_overdue_a_subset_of_not_filed():
    rows = [{"status": "pending", "due_date": "2026-07-31"}, {"status": "prepared", "due_date": "2027-01-31"},
            {"status": "filed", "due_date": "2026-07-31"}, {"status": "revised", "due_date": "2026-05-31"}]
    assert screen_counts.return_counts(rows, today=TODAY) == {"not_filed": 2, "filed": 2, "overdue": 1, "total": 4}


def test_the_certificate_count_is_the_ones_not_yet_issued():
    rows = [{"status": s} for s in ("pending", "generated", "issued", "downloaded", "pending")]
    assert screen_counts.certificate_counts(rows) == {"pending": 3, "total": 5}


# ── the windows, in the database path ───────────────────────────────────────

def _deductions_db(n=7):
    db = FakeDB()
    for i in range(n):
        db.seed("tds_deductions", {"id": f"d-{i}", "firm_id": FIRM, "client_id": CLIENT, "quarter": "Q1" if i % 2 else "Q2",
                                   "transaction_date": f"2026-06-{10 + i // 2:02d}", "payment_amount_paise": 1000 * (i + 1),
                                   "tds_paise": 100 * (i + 1)})
    db.seed("tds_deductions", {"id": "other-client", "firm_id": FIRM, "client_id": "CLIENT-2", "transaction_date": "2026-06-30",
                               "payment_amount_paise": 999_999, "tds_paise": 99_999})
    db.seed("tds_deductions", {"id": "other-firm", "firm_id": "FIRM-B", "client_id": CLIENT, "transaction_date": "2026-06-30",
                               "payment_amount_paise": 888_888, "tds_paise": 88_888})
    return db


def test_deductions_come_latest_day_first_then_by_id_and_a_window_never_repeats_or_skips():
    db = _deductions_db()
    first = lists.deductions(db, FIRM, CLIENT, quarter=None, limit=3, offset=0)
    second = lists.deductions(db, FIRM, CLIENT, quarter=None, limit=3, offset=3)
    third = lists.deductions(db, FIRM, CLIENT, quarter=None, limit=3, offset=6)
    ids = [r["id"] for w in (first, second, third) for r in w["deductions"]]
    # Latest day first (13, 12, 12, 11, 11, 10, 10 June), and the id ascending within a day.
    assert ids == ["d-6", "d-4", "d-5", "d-2", "d-3", "d-0", "d-1"], ids
    assert len(ids) == len(set(ids)) == 7, "every row once, none twice"
    assert (first["has_more"], second["has_more"], third["has_more"]) == (True, True, False)
    assert (first["limit"], first["max_limit"]) == (3, lists.TDS_LIST_MAX)


class _Capped:
    """A query that, like PostgREST, answers at most `cap` rows to one request and says nothing when it cuts one short."""
    def __init__(self, query, cap):
        self._query, self._cap = query, cap

    def __getattr__(self, name):
        attr = getattr(self._query, name)
        if not callable(attr):
            return attr

        def call(*args, **kwargs):
            out = attr(*args, **kwargs)
            if name == "execute":
                out.data = list(out.data or [])[: self._cap]
                return out
            return _Capped(out, self._cap) if hasattr(out, "execute") else out
        return call


class _CappedDB:
    def __init__(self, db, cap=1000):
        self._db, self._cap = db, cap

    def table(self, name):
        return _Capped(self._db.table(name), self._cap)


def _many(n):
    db = FakeDB()
    for i in range(n):
        db.seed("tds_deductions", {"id": f"d-{i:05d}", "firm_id": FIRM, "client_id": CLIENT,
                                   "transaction_date": f"2026-0{1 + i % 9}-{10 + i % 15}", "payment_amount_paise": 1, "tds_paise": 1})
    return _CappedDB(db), db


def test_a_window_longer_than_one_response_is_read_in_pages_and_has_more_tells_the_truth():
    capped, _db = _many(1500)
    whole = lists.deductions(capped, FIRM, CLIENT, quarter=None, limit=2000, offset=0)
    assert len(whole["deductions"]) == 1500 and whole["has_more"] is False, "1,500 rows asked for as 2,000 are all returned"
    assert len({r["id"] for r in whole["deductions"]}) == 1500, "no row twice across the page boundary"
    assert whole["totals"]["count"] == 1500
    part = lists.deductions(capped, FIRM, CLIENT, quarter=None, limit=1200, offset=0)
    assert len(part["deductions"]) == 1200 and part["has_more"] is True, "a window shorter than the register says more exist"


def test_a_register_longer_than_the_ceiling_is_cut_at_it_and_says_so():
    capped, _db = _many(2300)
    out = lists.deductions(capped, FIRM, CLIENT, quarter=None, limit=lists.TDS_LIST_MAX, offset=0)
    assert len(out["deductions"]) == lists.TDS_LIST_MAX and out["has_more"] is True
    assert out["totals"]["count"] == 2300, "the footer is over every row, and the notice says the table is not"
    rest = lists.deductions(capped, FIRM, CLIENT, quarter=None, limit=500, offset=2000)
    assert len(rest["deductions"]) == 300 and rest["has_more"] is False


def test_two_rows_of_one_day_are_ordered_by_id_whatever_order_they_were_stored_in():
    db = FakeDB()
    for rid in ("z", "m", "a"):
        db.seed("tds_deductions", {"id": rid, "firm_id": FIRM, "client_id": CLIENT, "transaction_date": "2026-06-10",
                                   "payment_amount_paise": 1, "tds_paise": 1})
    first = lists.deductions(db, FIRM, CLIENT, quarter=None, limit=2, offset=0)
    rest = lists.deductions(db, FIRM, CLIENT, quarter=None, limit=2, offset=2)
    assert [r["id"] for r in first["deductions"]] + [r["id"] for r in rest["deductions"]] == ["a", "m", "z"]
    mem = lists.deductions_in_memory(list(reversed(db.rows("tds_deductions"))), quarter=None, limit=5, offset=0)
    assert [r["id"] for r in mem["deductions"]] == ["a", "m", "z"], "the in-memory store orders the same way"


def test_the_totals_are_over_all_of_the_clients_deductions_and_not_the_window():
    db = _deductions_db()
    window = lists.deductions(db, FIRM, CLIENT, quarter=None, limit=2, offset=0)
    assert len(window["deductions"]) == 2
    assert window["totals"] == {"count": 7, "payment_amount_paise": 1000 * 28, "tds_paise": 100 * 28}, (
        "the footer describes the whole register, another client's and another firm's rows are not in it")


def test_a_quarter_narrows_the_list_and_the_totals_alike():
    db = _deductions_db()
    q1 = lists.deductions(db, FIRM, CLIENT, quarter="Q1", limit=50, offset=0)
    assert {r["quarter"] for r in q1["deductions"]} == {"Q1"}
    assert q1["totals"]["count"] == len(q1["deductions"]) == 3


def test_challans_are_latest_payment_first_and_the_date_bounds_apply():
    db = FakeDB()
    for n, day in enumerate(("2026-05-07", "2026-07-07", "2026-06-07")):
        db.seed("tds_challans", {"id": f"c-{n}", "firm_id": FIRM, "client_id": CLIENT, "payment_date": day, "total_paise": 100})
    out = lists.challans(db, FIRM, CLIENT, from_date=None, to_date=None, limit=50, offset=0)
    assert [c["payment_date"] for c in out["challans"]] == ["2026-07-07", "2026-06-07", "2026-05-07"]
    bounded = lists.challans(db, FIRM, CLIENT, from_date="2026-06-01", to_date="2026-06-30", limit=50, offset=0)
    assert [c["id"] for c in bounded["challans"]] == ["c-2"]
    assert "totals" not in out and "counts" not in out


def test_the_returns_counts_are_over_all_rows_and_overdue_is_the_indian_day(monkeypatch):
    monkeypatch.setattr(lists, "ist_today", lambda: TODAY)
    db = FakeDB()
    for n, (status, due) in enumerate([("pending", "2026-07-31"), ("filed", "2026-07-31"), ("prepared", "2026-10-31"),
                                        ("pending", "2026-10-20"), ("revised", "2026-01-31")]):
        db.seed("tds_returns", {"id": f"r-{n}", "firm_id": FIRM, "client_id": CLIENT, "status": status, "due_date": due})
    db.seed("tds_returns", {"id": "x", "firm_id": FIRM, "client_id": "CLIENT-2", "status": "pending", "due_date": "2020-01-01"})
    db.seed("tds_returns", {"id": "y", "firm_id": "FIRM-B", "client_id": CLIENT, "status": "pending", "due_date": "2020-01-01"})
    out = lists.returns(db, FIRM, CLIENT, limit=1, offset=0)
    assert len(out["returns"]) == 1 and out["has_more"] is True
    assert out["counts"] == {"not_filed": 3, "filed": 2, "overdue": 1, "total": 5}, "a window of one still counts all five"
    every = lists.returns(db, FIRM, CLIENT, limit=50, offset=0)
    assert sorted(r["id"] for r in every["returns"]) == [f"r-{n}" for n in range(5)], "another client's and another firm's returns are not listed"


def test_the_day_overdue_is_judged_on_is_the_one_ist_today_gives(monkeypatch):
    """Not the server's own date: the same returns read on two Indian days give two answers."""
    db = FakeDB()
    db.seed("tds_returns", {"id": "r", "firm_id": FIRM, "client_id": CLIENT, "status": "pending", "due_date": "2026-07-31"})
    monkeypatch.setattr(lists, "ist_today", lambda: date(2026, 7, 31))
    assert lists.returns(db, FIRM, CLIENT, limit=5, offset=0)["counts"]["overdue"] == 0
    assert lists.returns_in_memory([db.rows("tds_returns")[0]], limit=5, offset=0)["counts"]["overdue"] == 0
    monkeypatch.setattr(lists, "ist_today", lambda: date(2026, 8, 1))
    assert lists.returns(db, FIRM, CLIENT, limit=5, offset=0)["counts"]["overdue"] == 1
    assert lists.returns_in_memory([db.rows("tds_returns")[0]], limit=5, offset=0)["counts"]["overdue"] == 1


def test_the_certificates_pending_count_is_over_all_rows():
    db = FakeDB()
    db.seed("tds_certificates", {"id": "other-firm", "firm_id": "FIRM-B", "client_id": CLIENT, "status": "pending",
                                 "created_at": "2026-10-09T00:00:00+00:00"})
    db.seed("tds_certificates", {"id": "other-client", "firm_id": FIRM, "client_id": "CLIENT-2", "status": "pending",
                                 "created_at": "2026-10-09T00:00:00+00:00"})
    for n, status in enumerate(("pending", "generated", "issued", "pending")):
        db.seed("tds_certificates", {"id": f"k-{n}", "firm_id": FIRM, "client_id": CLIENT, "status": status,
                                     "created_at": f"2026-10-0{n + 1}T00:00:00+00:00"})
    out = lists.certificates(db, FIRM, CLIENT, limit=2, offset=0)
    assert [c["id"] for c in out["certificates"]] == ["k-3", "k-2"], "newest first"
    assert out["counts"] == {"pending": 3, "total": 4}


# ── the same answers in the in-memory path, through the routes ──────────────

@pytest.fixture
def mock_stores(monkeypatch):
    monkeypatch.setattr(tw, "_USE_MOCK", True)
    for name in ("_MOCK_DEDUCTIONS", "_MOCK_CHALLANS", "_MOCK_RETURNS", "_MOCK_CERTIFICATES"):
        monkeypatch.setattr(tw, name, {})
    monkeypatch.setattr(lists, "ist_today", lambda: TODAY)
    monkeypatch.setattr(tw, "assert_client_access", lambda *a, **k: None)


def test_the_routes_answer_windows_with_the_figures_in_the_in_memory_path(mock_stores):
    for i in range(4):
        tw._MOCK_DEDUCTIONS[f"d{i}"] = {"id": f"d{i}", "client_id": CLIENT, "transaction_date": f"2026-06-0{i + 1}",
                                       "payment_amount_paise": 100, "tds_paise": 10, "quarter": "Q1"}
    tw._MOCK_DEDUCTIONS["z"] = {"id": "z", "client_id": "CLIENT-2", "transaction_date": "2026-06-09", "payment_amount_paise": 1, "tds_paise": 1}
    tw._MOCK_RETURNS["r"] = {"id": "r", "client_id": CLIENT, "status": "pending", "due_date": "2026-07-31",
                             "return_type": "26Q", "financial_year": "2025-26"}
    tw._MOCK_CERTIFICATES["k"] = {"id": "k", "client_id": CLIENT, "status": "pending", "created_at": "2026-10-01",
                                  "certificate_type": "16A", "financial_year": "2025-26"}
    ded = tw.list_deductions(client_id=CLIENT, quarter=None, limit=2, offset=0, current_user=CALLER)["data"]
    assert [d["id"] for d in ded["deductions"]] == ["d3", "d2"] and ded["has_more"] is True
    assert ded["totals"] == {"count": 4, "payment_amount_paise": 400, "tds_paise": 40}
    ret = tw.list_returns(client_id=CLIENT, limit=50, offset=0, current_user=CALLER)["data"]
    assert ret["counts"]["overdue"] == 1 and ret["returns"][0]["statement_form"]
    cert = tw.list_certificates(client_id=CLIENT, limit=50, offset=0, current_user=CALLER)["data"]
    assert cert["counts"] == {"pending": 1, "total": 1}
    chal = tw.list_challans(client_id=CLIENT, from_date=None, to_date=None, limit=50, offset=0, current_user=CALLER)["data"]
    assert chal["challans"] == [] and chal["has_more"] is False and chal["max_limit"] == lists.TDS_LIST_MAX


def test_the_database_path_of_the_routes_passes_the_caller_s_filters_on(monkeypatch):
    """The routes in front of a real database: the quarter narrows the deductions and the dates bound the challans."""
    db = _deductions_db()
    for n, day in enumerate(("2026-05-07", "2026-07-07", "2026-06-07")):
        db.seed("tds_challans", {"id": f"c-{n}", "firm_id": FIRM, "client_id": CLIENT, "payment_date": day, "total_paise": 100})
    import core.supabase_client as sc
    monkeypatch.setattr(tw, "_USE_MOCK", False)
    monkeypatch.setattr(sc, "get_supabase", lambda: db)
    monkeypatch.setattr(tw, "assert_client_access", lambda *a, **k: None)
    q1 = tw.list_deductions(client_id=CLIENT, quarter="Q1", limit=50, offset=0, current_user=CALLER)["data"]
    assert {d["quarter"] for d in q1["deductions"]} == {"Q1"} and q1["totals"]["count"] == 3
    bounded = tw.list_challans(client_id=CLIENT, from_date="2026-06-01", to_date="2026-06-30", limit=50, offset=0,
                               current_user=CALLER)["data"]
    assert [c["id"] for c in bounded["challans"]] == ["c-2"]
    ret = tw.list_returns(client_id=CLIENT, limit=50, offset=0, current_user=CALLER)["data"]
    cert = tw.list_certificates(client_id=CLIENT, limit=50, offset=0, current_user=CALLER)["data"]
    assert ret["returns"] == [] and ret["counts"]["total"] == 0 and cert["certificates"] == []


def test_the_ceiling_is_the_one_the_browser_asks_for():
    """Held from the other end by `scripts/a-list-that-stops-at-a-number-says-so.test.ts`; said here as well so a change to either
    number fails in whichever language it is made in."""
    from pathlib import Path
    window = (Path(__file__).resolve().parents[2] / "web" / "lib" / "lists" / "window.ts").read_text(encoding="utf-8")
    import re
    browser = re.search(r"export const TDS_REGISTER_WINDOW_MAX = (\d+);", window)
    assert browser and int(browser.group(1)) == lists.TDS_LIST_MAX


def test_the_routes_accept_the_ceiling_and_nothing_above_it():
    import inspect
    for fn in (tw.list_deductions, tw.list_challans, tw.list_returns, tw.list_certificates):
        limit = inspect.signature(fn).parameters["limit"].default
        metadata = {type(m).__name__: m for m in limit.metadata}
        assert metadata["Le"].le == lists.TDS_LIST_MAX and metadata["Ge"].ge == 1, fn.__name__
    assert lists.TDS_LIST_MAX >= 500


# ── the section names and the sections a challan may be recorded under ──────

def test_every_section_the_registry_holds_has_a_name_in_every_year():
    unnamed = sorted({sec for rates in TDS_RATES_BY_FY.values() for sec in rates.sections
                      if label_of(sec, rates.fy) is None})
    assert unnamed == [], f"these registry sections have no plain-English name in domain/tds/section_labels.py: {unnamed}"


def test_a_clause_key_takes_the_name_of_its_section():
    assert label_of("194J(A)") == SECTION_LABELS["194J"] == label_of("194j")
    assert label_of("nonsense") is None and label_of(None) is None and label_of("") is None


def test_a_challan_may_be_recorded_under_194T_and_195_and_each_section_once():
    offered = [c["section"] for c in challan_sections("2026-27")]
    assert "194T" in offered and "195" in offered and "192" in offered and "206C" in offered
    assert len(offered) == len(set(offered)), "a parent is offered once, not once per limb"
    assert not any("(" in sec for sec in offered), "a challan names the section a CA would type, not the limb of a bill"
    assert offered[-1] == "195", "§195, which the resident registry does not hold, follows the registry's sections"
    assert all(c["label"] for c in challan_sections("2026-27"))
    assert {parent_of(k, "2026-27") for k in TDS_RATES_BY_FY["2026-27"].sections} <= set(offered)


def test_the_sections_endpoint_serves_the_names_and_the_challan_list():
    from routers import tds
    data = tds.list_tds_sections(fy="2026-27", user=CALLER)["data"]
    assert [s["label"] for s in data["sections"] if s["section"] == "194J(A)"] == ["Professional / technical fees"]
    assert all(s["label"] for s in data["sections"])
    assert data["challan_sections"] == challan_sections(data["fy"])


# ── core.db_paging.fetch_window: the one reader of a window the register lists use ─────────────────────────────

class _Ranges:
    """A query builder that records each `.order()` and `.range()` it is given and answers from a table of `total` rows."""
    def __init__(self, total, log):
        self.total, self.log, self.orders = total, log, []
        self.start = self.stop = 0

    def order(self, *args, **kwargs):
        self.orders.append((args, kwargs))
        return self

    def range(self, start, stop):
        self.start, self.stop = start, stop
        return self

    def execute(self):
        from types import SimpleNamespace
        self.log.append((self.start, self.stop, list(self.orders)))
        return SimpleNamespace(data=[{"id": i} for i in range(self.start, min(self.stop + 1, self.total))])


def test_fetch_window_never_asks_for_more_than_a_page_and_walks_the_window_in_order():
    from core import db_paging
    log: list = []
    rows = db_paging.fetch_window(lambda: _Ranges(10_000, log), "transaction_date", count=2500, start=0)
    assert [(a, b) for a, b, _ in log] == [(0, 999), (1000, 1999), (2000, 2499)]
    assert all(b - a + 1 <= db_paging.PAGE for a, b, _ in log)
    assert [r["id"] for r in rows] == list(range(2500)), "every row once, in order"
    assert all(o == [(("transaction_date",), {"desc": True}), (("id",), {})] for _, _, o in log), "the day descending, then the id"


def test_fetch_window_stops_on_a_short_page_and_starts_where_it_is_told():
    from core import db_paging
    log: list = []
    rows = db_paging.fetch_window(lambda: _Ranges(1700, log), "due_date", count=2500, start=0, desc=False)
    assert len(rows) == 1700 and [(a, b) for a, b, _ in log] == [(0, 999), (1000, 1999)], "the short second page ends the walk"
    assert log[0][2][0] == (("due_date",), {"desc": False})
    log.clear()
    assert [r["id"] for r in db_paging.fetch_window(lambda: _Ranges(10_000, log), "d", count=10, start=3000)] == list(range(3000, 3010))
    assert [(a, b) for a, b, _ in log] == [(3000, 3009)]
    log.clear()
    assert db_paging.fetch_window(lambda: _Ranges(10, log), "d", count=0) == [] and log == [], "an empty window asks nothing"
