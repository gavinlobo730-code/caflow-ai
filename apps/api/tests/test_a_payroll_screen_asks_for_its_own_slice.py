"""PAY-16 — no payroll screen loads every payslip the firm ever produced.

WHAT WAS WRONG
    Both firm-level payroll screens did exactly that, on mount.

    /payroll issued one `GET /runs/{id}/slips` PER RUN, concurrently, to render
    a tab that is not even the default — and every one of its five figures per
    run is an AGGREGATE: how many slips, the gross, the TDS, how many carried
    PF, how many carried ESI. Five numbers, fetched as N rows of every column.

    /payroll/reports put every run's UUID into one PostgREST `in.()` and pulled
    the lot, before any tab had been chosen. Its five tabs then each looked at
    a slice: one run, one month, one employee's financial year.

    CLAUDE.md: "No report may fetch rows proportional to transaction volume.
    What crosses the wire must be proportional to the size of the ANSWER." A
    hundred employees over three years is 3,600 payslips to render a table of a
    dozen rows.

THE FIX IS A REFUSAL, NOT A GUARD ON ONE
    GET /api/payroll/slips will not answer a request that names no run, no
    month and no employee. Every screen that shows payslips shows a slice; an
    endpoint that will hand over the whole table is one the next screen asks.

FOUR TABS FETCH ROWS AND ONE AGGREGATES, AND THE LINE BETWEEN THEM IS THE POINT
    A run's payslips, a month's, one employee's twelve months — each is a row
    set the same size as the table it renders, so fetching the rows IS fetching
    the answer. A firm's whole financial year is not, so the year-end summary
    is computed server-side.
"""
from __future__ import annotations

import pathlib

import pytest

from services import payroll_report_service as prs

WEB = pathlib.Path(__file__).resolve().parents[3] / "apps" / "web"
FIRM = "11111111-1111-1111-1111-111111111111"


# ── The refusal ─────────────────────────────────────────────────────────────

def test_a_payslip_read_must_name_what_it_is_about():
    with pytest.raises(prs.PayrollReportRefused) as e:
        prs.assert_narrowed(None, None, None)
    msg = str(e.value)
    assert "run" in msg and "month" in msg and "employee" in msg


@pytest.mark.parametrize("kw", [
    {"run_id": "r1"}, {"month": "2026-04"}, {"employee_id": "e1"},
])
def test_any_one_of_the_three_is_enough(kw):
    prs.assert_narrowed(kw.get("run_id"), kw.get("month"), kw.get("employee_id"))


@pytest.mark.parametrize("bad", ["2026-13", "2026-00", "202604", "2026-4", "April"])
def test_a_month_that_is_not_a_month_is_refused(bad):
    with pytest.raises(prs.PayrollReportRefused):
        prs.assert_narrowed(None, bad, None)


# ── The aggregate ───────────────────────────────────────────────────────────

class _Q:
    def __init__(self, rows):
        self.rows, self.calls = rows, []

    def select(self, *a): self.calls.append(("select", *a)); return self
    def eq(self, k, v): self.calls.append(("eq", k, v)); return self
    def in_(self, k, v): self.calls.append(("in_", k, list(v))); return self
    def order(self, *a, **k): return self

    def execute(self):
        class _R:
            data = self.rows
        return _R()


class _DB:
    def __init__(self, by_table):
        self.by_table, self.qs = by_table, {}

    def table(self, name):
        q = _Q(self.by_table.get(name, []))
        self.qs.setdefault(name, []).append(q)
        return q


def _slip(run_id, **kw):
    base = {"run_id": run_id, "gross_paise": 0, "net_paise": 0, "tds_paise": 0,
            "pf_employee_paise": 0, "pf_employer_paise": 0,
            "esi_employee_paise": 0, "esi_employer_paise": 0}
    base.update(kw)
    return base


def test_the_summary_is_one_query_for_every_run_asked_about():
    """The screen this replaced made one request PER RUN, each returning every
    column of every payslip in it."""
    db = _DB({"payroll_slips": [
        _slip("r1", gross_paise=5000000, tds_paise=100000, pf_employee_paise=180000),
        _slip("r1", gross_paise=3000000, esi_employee_paise=22500),
        _slip("r2", gross_paise=1000000),
    ]})
    out = prs.run_summaries(db, FIRM, ["r1", "r2"])
    assert len(db.qs["payroll_slips"]) == 1
    assert out["r1"]["slip_count"] == 2
    assert out["r1"]["gross_paise"] == 8000000
    assert out["r1"]["tds_paise"] == 100000
    assert out["r2"]["slip_count"] == 1


def test_a_run_with_no_slips_is_a_zero_row_not_a_missing_one():
    """The table lists every run; a month with nothing in it reads as 0, and
    an absent key would render as blank or crash the row."""
    db = _DB({"payroll_slips": []})
    out = prs.run_summaries(db, FIRM, ["r1"])
    assert out["r1"]["slip_count"] == 0
    assert out["r1"]["gross_paise"] == 0


def test_the_member_counts_are_what_the_slip_carried():
    """NOT a re-derived ceiling test.

    The browser's old test was `gross <= 2100000` for the month, which drops a
    member ESI Rule 50 keeps in past the ceiling until the contribution period
    ends — so the button read "no ESI-applicable employees" for people the firm
    had deducted from. The slip is the record of what was deducted.
    """
    db = _DB({"payroll_slips": [
        # Well over the ESI ceiling, and the firm deducted anyway: Rule 50.
        _slip("r1", gross_paise=9000000, esi_employee_paise=67500),
        _slip("r1", gross_paise=1000000, pf_employee_paise=120000),
        _slip("r1", gross_paise=1000000),
    ]})
    out = prs.run_summaries(db, FIRM, ["r1"])
    assert out["r1"]["esi_count"] == 1
    assert out["r1"]["pf_count"] == 1


def test_an_employer_only_esi_contribution_still_counts_the_member():
    db = _DB({"payroll_slips": [_slip("r1", esi_employer_paise=32500)]})
    assert prs.run_summaries(db, FIRM, ["r1"])["r1"]["esi_count"] == 1


def test_no_runs_asks_nothing():
    db = _DB({})
    assert prs.run_summaries(db, FIRM, []) == {}
    assert "payroll_slips" not in db.qs


def test_the_year_end_summary_is_one_row_per_employee():
    db = _DB({
        "payroll_runs": [{"id": "r1", "client_id": "c1", "month": "2026-04",
                          "financial_year": "2026-27"},
                         {"id": "r2", "client_id": "c1", "month": "2026-05",
                          "financial_year": "2026-27"}],
        "payroll_slips": [
            {"employee_id": "e1", "gross_paise": 5000000, "net_paise": 4500000,
             "tds_paise": 200000, "pt_paise": 20000, "pf_employee_paise": 180000,
             "esi_employee_paise": 0,
             "payroll_employees": {"name": "Asha", "pan": "ABCPK1234F",
                                   "designation": "Manager"}},
            {"employee_id": "e1", "gross_paise": 5000000, "net_paise": 4500000,
             "tds_paise": 200000, "pt_paise": 20000, "pf_employee_paise": 180000,
             "esi_employee_paise": 0,
             "payroll_employees": {"name": "Asha", "pan": "ABCPK1234F",
                                   "designation": "Manager"}},
            {"employee_id": "e2", "gross_paise": 1000000, "net_paise": 950000,
             "tds_paise": 0, "pt_paise": 20000, "pf_employee_paise": 120000,
             "esi_employee_paise": 7500,
             "payroll_employees": {"name": "Bhaskar", "pan": "ABCPK9999F",
                                   "designation": "Executive"}},
        ]})
    rows = prs.employee_year_totals(db, FIRM, "2026-27")
    assert [r["employee_id"] for r in rows] == ["e1", "e2"]   # sorted by name
    asha = rows[0]
    assert asha["months"] == 2
    assert asha["gross_paise"] == 10000000
    assert asha["tds_paise"] == 400000
    assert asha["employee"]["name"] == "Asha"


def test_a_year_with_no_runs_reads_nothing_rather_than_everything():
    db = _DB({"payroll_runs": []})
    assert prs.employee_year_totals(db, FIRM, "2019-20") == []
    assert "payroll_slips" not in db.qs


def test_the_year_options_come_off_the_runs():
    """One row per client-month, not one per payslip. The picker used to derive
    its options from every payslip the firm had ever produced.

    And the year is derived from `month`, because payroll_runs has no
    financial_year column — March 2027 is FY 2026-27, so the two months below
    collapse to ONE option rather than looking like two years of payroll.
    """
    db = _DB({"payroll_runs": [{"month": "2025-06"},
                               {"month": "2026-04"},
                               {"month": "2027-03"},
                               {"month": None}]})
    assert prs.financial_years(db, FIRM) == ["2026-27", "2025-26"]


# ── The screens ─────────────────────────────────────────────────────────────

def _web(*parts: str) -> str:
    return (WEB.joinpath(*parts)).read_text(encoding="utf-8")


def test_the_payroll_page_no_longer_fetches_every_payslip():
    page = _web("app", "payroll", "page.tsx")
    assert "getRunSlips" not in page, "still fetching one run's slips at a time"
    assert "api.payroll.runSummaries(" in page


def test_the_reports_page_no_longer_fetches_every_payslip():
    page = _web("app", "payroll", "reports", "page.tsx")
    assert 'from("payroll_slips")' not in page, (
        "still reading payroll_slips straight from PostgREST")
    assert "useSlips(" in page
    assert "api.payroll.yearEndSummary(" in page


def test_every_reports_tab_asks_for_one_thing():
    """Three narrow slip reads, one aggregate, and one served projection.

    The TDS Projection tab used to be the fourth slip read —
    `useSlips({ employee_id: selectedEmpId })` — and it pulled that employee's
    whole history so the BROWSER could estimate §192 from its own slab ladder
    (PAY-10). It asks the server for the projection now, which is one narrow
    question about one employee and one year, so the rule this test states is
    unchanged and the shape of the answer is not.
    """
    page = _web("app", "payroll", "reports", "page.tsx")
    for slice_ in ("{ run_id: selectedRunId }",
                   "{ employee_id: selectedEmpId, financial_year: selectedFy }",
                   "{ month: selectedMonth }"):
        assert slice_ in page, f"no tab asks for {slice_}"
    assert "api.payroll.tdsProjection(emp.client_id, selectedEmpId, selectedFy)" in page, (
        "the projection tab must ask the server for one employee and one year")
    assert "payrollTdsEstimate" not in page.replace(
        "lib/services/payrollTdsEstimate.ts", ""), (
        "the browser §192 estimator is back")


def test_a_failed_slice_is_not_an_empty_table():
    """An empty table under a real employee's name reads as 'this employee had
    no payroll' — a statement, and a false one."""
    page = _web("app", "payroll", "reports", "page.tsx")
    assert page.count("<SliceState") >= 5
    hook = _web("lib", "payroll", "useSlips.ts")
    assert "setSlips([]);" in hook, "stale rows survive a failed fetch"


def test_the_browser_never_sends_an_unnarrowed_request():
    """The server refuses one; this makes sure it is never asked."""
    hook = _web("lib", "payroll", "useSlips.ts")
    assert "export function isNarrowed" in hook
    assert "if (!key) { setSlips([]); setError(null); return; }" in hook


# ── The financial year is DERIVED, because there is no column for it ────────

def test_the_financial_year_comes_off_the_month():
    """payroll_runs has NO financial_year column.

    It carries `month` and nothing else about the year. The first draft of this
    module filtered on `.eq("financial_year", ...)` and
    tests/test_backend_columns_exist_pg.py caught it against the real schema —
    which is what that checker is for.
    """
    assert prs.fy_of_month("2026-04") == "2026-27"
    assert prs.fy_of_month("2026-12") == "2026-27"


def test_january_to_march_belong_to_the_year_that_started_last_april():
    """The Indian FY runs 1 April to 31 March.

    Reading the first four characters files March 2027 under 2027-28 — a year
    with no payroll in it — which is the same off-by-a-year the payroll month
    picker had before financialYearOfMonth was written.
    """
    assert prs.fy_of_month("2027-01") == "2026-27"
    assert prs.fy_of_month("2027-03") == "2026-27"
    assert prs.fy_of_month("2027-04") == "2027-28"


def test_a_month_that_is_not_a_month_gets_no_year():
    for bad in ("", "2026", "2026-13", "March 2027", None):
        assert prs.fy_of_month(bad) is None       # type: ignore[arg-type]


def test_a_year_is_twelve_months_starting_in_april():
    months = prs.months_of_fy("2026-27")
    assert len(months) == 12
    assert months[0] == "2026-04"
    assert months[-1] == "2027-03"
    assert all(prs.fy_of_month(m) == "2026-27" for m in months)


def test_a_year_label_that_is_not_one_yields_no_months():
    assert prs.months_of_fy("garbage") == []
