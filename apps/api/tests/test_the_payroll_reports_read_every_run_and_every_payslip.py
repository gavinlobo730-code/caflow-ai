"""POST-A-535: the payroll reports read every run and every payslip, however many there are.

WHAT WAS WRONG
    The year-end pay report, its list of years and the table of runs each read their rows in ONE request. The database answers at most a
    thousand rows to a request and says nothing about the rest, so past that the report added up part of a year, the list of years lost
    years and the table of runs lost months, with no word on the screen. A hundred clients reach a thousand runs in under a year; a
    hundred employees reach a thousand payslips in ten months. And the ids of the runs went into one `in.()` filter, which is part of
    the address: a few hundred ids is a request the gateway refuses before the database sees it.

WHAT THESE TESTS HOLD
    A stand-in database that answers at most `CAP` rows to any one request, as the real one does, and can be walked a page at a time. Each
    report is asked for more rows than one request holds, and must count them all. The list of run ids must go in pieces. And the rule
    itself: nothing in the report service, and nothing in the route that lists the runs, sends a request of its own.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from core import db_paging
from services import payroll_report_service as prs

API = pathlib.Path(__file__).resolve().parents[1]
FIRM = "11111111-1111-1111-1111-111111111111"
CAP = 7          # the most rows one request is answered with, standing in for the database's thousand


class _Q:
    """One request being built. Filters are applied for real, and `execute` answers at most CAP rows."""

    def __init__(self, db, rows):
        self.db, self.rows, self._limit, self._order = db, list(rows), None, None

    def select(self, *a): return self
    def eq(self, k, v): self.rows = [r for r in self.rows if str(r.get(k)) == str(v)]; return self

    def in_(self, k, v):
        wanted = {str(x) for x in v}
        self.db.in_sizes.append(len(wanted))
        self.rows = [r for r in self.rows if str(r.get(k)) in wanted]
        return self

    def gt(self, k, v): self.rows = [r for r in self.rows if str(r.get(k)) > str(v)]; return self
    def order(self, k, **kw): self._order = k; return self
    def limit(self, n): self._limit = n; return self

    def execute(self):
        self.db.requests += 1
        rows = sorted(self.rows, key=lambda r: str(r.get(self._order))) if self._order else self.rows
        answered = rows[:min(self._limit or CAP, CAP)]

        class _R:
            data = answered
        return _R()


class _DB:
    def __init__(self, by_table):
        self.by_table, self.requests, self.in_sizes = by_table, 0, []

    def table(self, name):
        return _Q(self, self.by_table.get(name, []))


@pytest.fixture(autouse=True)
def _a_page_is_what_one_request_answers(monkeypatch):
    monkeypatch.setattr(db_paging, "PAGE", CAP)


def _slip(n, run_id, employee_id="e1", **kw):
    base = {"id": f"s{n:05d}", "run_id": run_id, "employee_id": employee_id, "gross_paise": 100, "net_paise": 90, "tds_paise": 1,
            "pt_paise": 0, "pf_employee_paise": 0, "pf_employer_paise": 0, "esi_employee_paise": 0, "esi_employer_paise": 0,
            "payroll_employees": {"name": employee_id}}
    base.update(kw)
    return base


def test_the_year_end_report_adds_up_every_payslip_of_the_year():
    """Thirty payslips where one request answers seven: the year's gross is all thirty, not the first seven."""
    db = _DB({"payroll_runs": [{"id": "r1", "firm_id": FIRM, "client_id": "c1", "month": "2026-04"}],
              "payroll_slips": [_slip(n, "r1", employee_id=f"e{n % 3}") for n in range(30)]})
    rows = prs.employee_year_totals(db, FIRM, "2026-27", narrow=lambda runs: runs)
    assert sum(r["gross_paise"] for r in rows) == 30 * 100
    assert sum(r["months"] for r in rows) == 30
    assert len(rows) == 3


def test_the_year_end_report_reads_every_run_of_the_year():
    """Twenty-four runs (two clients, twelve months) where one request answers seven: the payslip of the last run is counted."""
    months = prs.months_of_fy("2026-27")
    runs = [{"id": f"r{c}{i:02d}", "firm_id": FIRM, "client_id": f"c{c}", "month": m} for c in (1, 2) for i, m in enumerate(months)]
    db = _DB({"payroll_runs": runs, "payroll_slips": [_slip(i, r["id"]) for i, r in enumerate(runs)]})
    rows = prs.employee_year_totals(db, FIRM, "2026-27", narrow=lambda rs: rs)
    assert rows[0]["months"] == 24 and rows[0]["gross_paise"] == 2400


def test_the_narrowing_is_given_every_run_and_decides_among_them():
    """The caller's narrowing must see the runs past the first request too, or a client whose runs come late is never answered for."""
    months = prs.months_of_fy("2026-27")
    runs = [{"id": f"r{c}{i:02d}", "firm_id": FIRM, "client_id": f"c{c}", "month": m} for c in (1, 2) for i, m in enumerate(months)]
    db = _DB({"payroll_runs": runs, "payroll_slips": [_slip(i, r["id"]) for i, r in enumerate(runs)]})
    seen: list[int] = []

    def only_the_second_client(rs):
        seen.append(len(rs))
        return [r for r in rs if r["client_id"] == "c2"]

    rows = prs.employee_year_totals(db, FIRM, "2026-27", narrow=only_the_second_client)
    assert seen == [24]
    assert rows[0]["months"] == 12


def test_the_list_of_years_holds_the_years_past_the_first_request():
    """Thirty-six runs over three years: all three years are offered, wherever their rows fall in the read."""
    runs = [{"id": f"r{n:03d}", "firm_id": FIRM, "client_id": "c1", "month": m}
            for n, m in enumerate(prs.months_of_fy("2024-25") + prs.months_of_fy("2025-26") + prs.months_of_fy("2026-27"))]
    db = _DB({"payroll_runs": runs})
    assert prs.financial_years(db, FIRM, narrow=lambda rs: rs) == ["2026-27", "2025-26", "2024-25"]


def test_the_table_of_runs_counts_every_payslip_of_a_run():
    db = _DB({"payroll_slips": [_slip(n, "r1" if n % 2 else "r2", pf_employee_paise=5) for n in range(40)]})
    out = prs.run_summaries(db, FIRM, ["r1", "r2"])
    assert out["r1"]["slip_count"] == 20 and out["r2"]["slip_count"] == 20
    assert out["r1"]["gross_paise"] == 2000 and out["r2"]["pf_count"] == 20


def test_a_long_list_of_runs_is_sent_in_pieces():
    """Four hundred run ids in one filter is an address the gateway refuses. No one request names more than the pager's piece."""
    run_ids = [f"r{n:04d}" for n in range(400)]
    db = _DB({"payroll_slips": [_slip(n, rid) for n, rid in enumerate(run_ids)]})
    out = prs.run_summaries(db, FIRM, run_ids)
    assert sum(b["slip_count"] for b in out.values()) == 400
    assert db.in_sizes and max(db.in_sizes) <= db_paging.IN_CHUNK


def test_one_request_really_is_short_in_this_stand_in():
    """The control: a single request over the stand-in answers CAP rows and no more, which is the fault the tests above would not see
    if the stand-in handed everything over at once."""
    db = _DB({"payroll_slips": [_slip(n, "r1") for n in range(30)]})
    assert len(db.table("payroll_slips").select("*").execute().data) == CAP


# ── The rule ─────────────────────────────────────────────────────────────────

def _own_requests(source: str) -> list[int]:
    """The line of every `.execute()` call in a piece of source: a request the code sends by itself, outside the pager."""
    return [n.lineno for n in ast.walk(ast.parse(source))
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "execute"]


def test_the_report_service_sends_no_request_of_its_own():
    """Every read of the service is the pager's. A new read written with `.execute()` is a read that stops at a thousand rows."""
    assert _own_requests((API / "services" / "payroll_report_service.py").read_text(encoding="utf8")) == []


def test_the_route_that_lists_the_runs_sends_no_request_of_its_own():
    from routers import payroll
    import textwrap
    assert _own_requests(textwrap.dedent(inspect.getsource(payroll.get_run_summaries))) == []


def test_the_rule_reader_sees_a_request():
    """The control for the two tests above."""
    assert _own_requests("rows = db.table('t').select('id').execute().data") == [1]
