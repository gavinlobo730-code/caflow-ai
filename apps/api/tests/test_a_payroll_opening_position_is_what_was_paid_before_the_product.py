"""A payroll opening position (POST-A-082, migration 641): what an employee had been paid and had deducted this financial year
before the client's payroll ran on this product.

The rules: it is validated against the calendar and the joining date; the engine reads it beside the released runs, and only for a
run month on or after its first month; the §192(3) spread then runs over the months that really remain; an employee with no
earlier month and no position is NAMED in the run's gaps; an unknown ESI answer is not a contribution; and it is a record, not a
run (nothing here posts).
"""
from __future__ import annotations

import pathlib
import re

import pytest

from domain.payroll import opening_position as O
from routers import payroll as P

FIRM, CLIENT, EMP = "f1", "c1", "e1"


def body(**over):
    base = dict(employee_id=EMP, first_month_here="2026-10", months_paid=6, gross_paise=6_000_000, tds_paise=120_000,
                pf_employee_paise=432_000, pf_employer_paise=432_000, esi_employee_paise=0, esi_employer_paise=0,
                pt_paise=7_200, esi_contributed_earlier_in_period=None, source_note="Tally payroll register, 30-09-2026")
    base.update(over)
    return base


# ── validation ────────────────────────────────────────────────────────────────

def test_a_position_for_the_months_before_the_first_month_is_acceptable():
    assert O.validate(body(), fy="2026-27", joining_date="2020-01-01") == []


def test_more_months_than_fall_before_the_first_month_is_refused():
    out = O.validate(body(months_paid=7), fy="2026-27", joining_date="2020-01-01")
    assert out and "only 6 month(s)" in out[0]


def test_a_joiner_cannot_have_been_paid_for_months_before_joining():
    out = O.validate(body(months_paid=4), fy="2026-27", joining_date="2026-08-10")      # Aug, Sep = 2
    assert out and "joined in 2026-08" in out[0] and "at most 2" in out[0]
    assert O.validate(body(months_paid=2), fy="2026-27", joining_date="2026-08-10") == []


def test_months_and_gross_go_together_and_tax_cannot_exceed_gross():
    assert any("go together" in m for m in O.validate(body(gross_paise=0, tds_paise=0, pf_employee_paise=0, pf_employer_paise=0,
                                                         pt_paise=0), fy="2026-27", joining_date=None))
    assert any("tax withheld" in m for m in O.validate(body(tds_paise=7_000_000), fy="2026-27", joining_date="2020-01-01"))
    assert any("own deductions" in m for m in O.validate(body(pf_employee_paise=6_000_000), fy="2026-27", joining_date="2020-01-01"))


def test_a_first_month_outside_the_year_a_negative_figure_and_an_unreadable_joining_date_are_refused():
    assert O.validate(body(first_month_here="2027-04"), fy="2026-27", joining_date=None)
    assert any("zero or more" in m for m in O.validate(body(pt_paise=-1), fy="2026-27", joining_date="2020-01-01"))
    assert any("joining date cannot be read" in m for m in O.validate(body(), fy="2026-27", joining_date="garbage"))


def test_a_nil_position_is_an_answer():
    z = body(months_paid=0, gross_paise=0, tds_paise=0, pf_employee_paise=0, pf_employer_paise=0, pt_paise=0)
    assert O.validate(z, fy="2026-27", joining_date="2026-10-01") == []


def test_a_yes_to_esi_earlier_in_the_period_is_refused_where_the_first_month_opens_the_period():
    """April and October open an ESI contribution period, so no earlier month of it exists: a Yes there describes the previous
    period, and continuation does not cross the boundary. A later first month may say Yes; No and Not known are always fine."""
    nil = dict(months_paid=0, gross_paise=0, tds_paise=0, pf_employee_paise=0, pf_employer_paise=0, pt_paise=0)
    for fy, b in (("2026-27", body(first_month_here="2026-10", esi_contributed_earlier_in_period=True)),
                  ("2027-28", body(first_month_here="2027-04", esi_contributed_earlier_in_period=True, **nil))):
        opens = b["first_month_here"]
        out = O.validate(b, fy=fy, joining_date="2020-01-01")
        assert any("opens an ESI contribution period" in m for m in out), (opens, out)
        for answer in (False, None):
            b["esi_contributed_earlier_in_period"] = answer
            assert not any("ESI" in m for m in O.validate(b, fy=fy, joining_date="2020-01-01")), (opens, answer)
    later = body(first_month_here="2026-11", months_paid=7, esi_contributed_earlier_in_period=True)
    assert O.validate(later, fy="2026-27", joining_date="2020-01-01") == []


# ── the engine reads it ─────────────────────────────────────────────────────────

class _Q:
    def __init__(self, rows):
        self.rows, self.preds = rows, []

    def select(self, *_):
        return self

    def eq(self, c, v):
        self.preds.append(lambda r: r.get(c) == v)
        return self

    def in_(self, c, vs):
        self.preds.append(lambda r: r.get(c) in list(vs))
        return self

    def execute(self):
        return type("R", (), {"data": [r for r in self.rows if all(p(r) for p in self.preds)]})()


class _DB:
    def __init__(self, **tables):
        self.t = tables

    def table(self, n):
        return _Q(self.t.get(n, []))


def position(**over):
    return {"firm_id": FIRM, "client_id": CLIENT, "employee_id": EMP, "financial_year": "2026-27", "first_month_here": "2026-10-01",
            "months_paid": 6, "gross_paise": 6_000_000, "tds_paise": 120_000, **over}


def test_the_ytd_reads_the_position_for_a_run_on_or_after_the_first_month_only():
    db = _DB(payroll_runs=[], payroll_slips=[], payroll_opening_positions=[position()])
    assert P._tds_already_deducted_this_fy(db, FIRM, CLIENT, "2026-10", "2026-27") == {EMP: (120_000, 6, 6_000_000)}
    assert P._tds_already_deducted_this_fy(db, FIRM, CLIENT, "2026-09", "2026-27") == {}


def test_released_months_here_add_to_the_position():
    runs = [{"id": "r1", "month": "2026-10", "status": "finalized"}, {"id": "r2", "month": "2026-11", "status": "draft"}]
    slips = [{"run_id": "r1", "employee_id": EMP, "tds_paise": 20_000, "gross_paise": 1_000_000}]
    db = _DB(payroll_runs=[{**r, "firm_id": FIRM, "client_id": CLIENT} for r in runs], payroll_slips=slips,
             payroll_opening_positions=[position()])
    assert P._tds_already_deducted_this_fy(db, FIRM, CLIENT, "2026-11", "2026-27") == {EMP: (140_000, 7, 7_000_000)}


_SLIP_EMP = {"id": EMP, "name": "Asha", "basic_paise": 10_00_000, "hra_percent": 0, "da_percent": 0, "lta_paise": 0,
             "medical_paise": 0, "special_allowance_paise": 0, "other_allowances_paise": 0, "pf_applicable": False,
             "esi_applicable": False, "pt_applicable": False, "joining_date": "2020-04-01"}


def _slip_through_the_run_path(db, monkeypatch, annual_tax=600_000):
    """The October slip, computed the way the run computes it: the YTD read off the database, handed to `_compute_slip`.
    The year's tax is held at a figure so what is measured is the spread and the estimate, not the slab ladder."""
    seen = {}

    def fixed(**kw):
        seen["annual_salary"] = kw["projected_annual_salary_paise"]
        return annual_tax
    monkeypatch.setattr(P.decl_domain, "withholding_tax_paise", fixed)
    ytd = P._tds_already_deducted_this_fy(db, FIRM, CLIENT, "2026-10", "2026-27")
    tds, months, gross = ytd.get(EMP, (0, 0, 0))
    slip = P._compute_slip(dict(_SLIP_EMP), None, fy="2026-27", pt_month=10, tds_already_deducted_paise=tds,
                           months_already_paid=months, gross_already_paid_paise=gross)
    return slip, seen["annual_salary"]


def test_the_spread_runs_over_the_months_that_remain_once_the_position_is_counted(monkeypatch):
    """The point of the item, through the run's own path: a position recorded for April to September makes the October slip
    withhold what is left of the year over the six months that remain, and estimate the year from what was paid plus what is to
    come. Without it the slip spreads the whole year over twelve, as if nothing had been paid."""
    with_position, annual_with = _slip_through_the_run_path(
        _DB(payroll_runs=[], payroll_slips=[], payroll_opening_positions=[position()]), monkeypatch)
    without, annual_without = _slip_through_the_run_path(
        _DB(payroll_runs=[], payroll_slips=[], payroll_opening_positions=[]), monkeypatch)
    assert with_position["tds_paise"] == (600_000 - 120_000) // 6 == 80_000
    assert without["tds_paise"] == 600_000 // 12 == 50_000
    monthly = with_position["gross_paise"]
    assert annual_with == 6_000_000 + monthly * 6, "the year is the position's gross and the six months still to come"
    assert annual_without == monthly * 12


def test_a_failed_position_read_leaves_the_ytd_as_it_was_and_does_not_fail_the_run():
    class Boom(_DB):
        def table(self, n):
            if n == "payroll_opening_positions":
                raise RuntimeError("down")
            return super().table(n)
    db = Boom(payroll_runs=[], payroll_slips=[])
    assert P._tds_already_deducted_this_fy(db, FIRM, CLIENT, "2026-10", "2026-27") == {}


def test_esi_coverage_counts_an_explicit_yes_in_the_same_contribution_period_and_never_an_unknown():
    yes = position(esi_contributed_earlier_in_period=True, first_month_here="2026-11-01", months_paid=7)
    unknown = position(esi_contributed_earlier_in_period=None, employee_id="e2", first_month_here="2026-11-01", months_paid=7)
    db = _DB(payroll_runs=[], payroll_slips=[], payroll_opening_positions=[yes, unknown])
    # ESI periods are Apr-Sep and Oct-Mar: a position starting in November (October behind it) covers a November and a
    # December run, and not a run before its first month.
    assert P._members_contributing_earlier_this_period(db, FIRM, CLIENT, "2026-11") == {EMP}
    assert P._members_contributing_earlier_this_period(db, FIRM, CLIENT, "2026-12") == {EMP}
    assert P._members_contributing_earlier_this_period(db, FIRM, CLIENT, "2026-10") == set()


def test_a_yes_on_a_position_that_opens_its_esi_period_is_not_a_contribution():
    """A row written before the validation refused it: first month October, Yes. No month of October to March comes before
    October, so the Yes can only be about April to September, and continuation does not cross the period boundary."""
    db = _DB(payroll_runs=[], payroll_slips=[],
             payroll_opening_positions=[position(esi_contributed_earlier_in_period=True)])
    assert P._members_contributing_earlier_this_period(db, FIRM, CLIENT, "2026-10") == set()
    assert P._members_contributing_earlier_this_period(db, FIRM, CLIENT, "2026-11") == set()


def test_a_failed_position_read_keeps_the_coverage_the_released_runs_establish():
    """The positions are read apart from the runs: a table that cannot be read costs what the positions say, never the October
    run's contribution that keeps the employee in for November."""
    class Boom(_DB):
        def table(self, n):
            if n == "payroll_opening_positions":
                raise RuntimeError("down")
            return super().table(n)
    db = Boom(payroll_runs=[{"id": "r10", "month": "2026-10", "status": "finalized", "firm_id": FIRM, "client_id": CLIENT}],
              payroll_slips=[{"run_id": "r10", "employee_id": EMP, "esi_employee_paise": 15_000}])
    assert P._members_contributing_earlier_this_period(db, FIRM, CLIENT, "2026-11") == {EMP}


# ── the gap ───────────────────────────────────────────────────────────────────

def test_an_employee_with_no_earlier_month_and_no_position_is_named():
    gap = P._opening_position_gap({"id": EMP, "name": "Asha", "joining_date": "2020-01-01"}, "2026-10", "2026-27", {})
    assert len(gap) == 1 and "Asha" in gap[0] and "opening position" in gap[0]


def test_a_failed_read_is_named_as_one_and_never_as_nothing_on_file():
    """`_tds_already_deducted_this_fy` answers an empty mapping when it cannot read the runs, and the runs alone when it cannot
    read the positions. Neither is "no earlier payroll and no position": the gap says the read failed, for every employee who
    could have had an earlier month, whether or not the runs it did read name them."""
    class Boom(_DB):
        def __init__(self, broken, **tables):
            super().__init__(**tables)
            self.broken = broken

        def table(self, n):
            if n == self.broken:
                raise RuntimeError("down")
            return super().table(n)
    e = {"id": EMP, "name": "Asha", "joining_date": "2020-01-01"}
    runs = [{"id": "r10", "month": "2026-10", "status": "finalized", "firm_id": FIRM, "client_id": CLIENT}]
    slips = [{"run_id": "r10", "employee_id": EMP, "tds_paise": 20_000, "gross_paise": 1_000_000}]
    for broken in ("payroll_runs", "payroll_opening_positions"):
        ytd = P._tds_already_deducted_this_fy(Boom(broken, payroll_runs=runs, payroll_slips=slips), FIRM, CLIENT, "2026-11",
                                              "2026-27")
        gap = P._opening_position_gap(e, "2026-11", "2026-27", ytd)
        assert len(gap) == 1 and "could not be read" in gap[0] and "no opening position is recorded" not in gap[0], (broken, gap)
        # April and a joiner of the month still have nothing to name.
        assert P._opening_position_gap(e, "2026-04", "2026-27", ytd) == []
        assert P._opening_position_gap({**e, "joining_date": "2026-11-02"}, "2026-11", "2026-27", ytd) == []
    readable = P._tds_already_deducted_this_fy(_DB(payroll_runs=runs, payroll_slips=slips), FIRM, CLIENT, "2026-11", "2026-27")
    assert P._opening_position_gap(e, "2026-11", "2026-27", readable) == []


def test_no_gap_in_april_for_a_joiner_this_month_for_one_with_history_or_with_a_nil_position():
    e = {"id": EMP, "name": "Asha", "joining_date": "2020-01-01"}
    assert P._opening_position_gap(e, "2026-04", "2026-27", {}) == []
    assert P._opening_position_gap({**e, "joining_date": "2026-10-05"}, "2026-10", "2026-27", {}) == []
    assert P._opening_position_gap(e, "2026-10", "2026-27", {EMP: (0, 0, 0)}) == []
    assert P._opening_position_gap({**e, "joining_date": None}, "2026-10", "2026-27", {})   # unreadable: cannot be ruled out


# ── a record, not a run ──────────────────────────────────────────────────────────────

def test_the_module_and_its_endpoints_post_nothing():
    src = (pathlib.Path(P.__file__).read_text())
    start = src.index('@router.get("/opening-positions")')
    end = src.index('@router.get("/one-time-earnings")')
    block = src[start:end]
    assert not re.search(r"journal|_create_journal|payroll_slips\"\)\.(insert|update)", block)
    assert "payroll_slips" in block        # it READS slips, to refuse a month counted twice


def test_the_migration_grants_a_signed_in_session_nothing():
    sql = (pathlib.Path(__file__).resolve().parents[1] / "migrations" /
           "641_a_client_that_joins_mid_year_carries_an_opening_position_per_employee.sql").read_text()
    assert re.search(r"REVOKE ALL ON public\.payroll_opening_positions FROM PUBLIC, anon, authenticated", sql)
    assert "TO authenticated;" not in sql.split("REVOKE ALL")[1]


# ── the release door refuses the overlap the other way round ─────────────────────────

_REL_FIRM, _REL_CLIENT = "FIRM-OP", "CLI-OP"
_REL_CALLER = {"firm_id": _REL_FIRM, "id": "u-1", "auth_user_id": "auth-1", "email": "ca@f.test", "role": "Partner"}


@pytest.fixture()
def rel_db(monkeypatch):
    from tests.e2e_harness import FakeDB, wire_e2e
    d = FakeDB()
    wire_e2e(monkeypatch, d, [P])
    monkeypatch.setenv("SUPABASE_URL", "test://db")
    # The year's rate gap is held off so the release measured is the overlap rule alone.
    monkeypatch.setattr(P, "income_tax_rate_gap", lambda fy: None)
    d.seed("clients", {"id": _REL_CLIENT, "firm_id": _REL_FIRM, "financial_year_start": "2026-04-01"})
    d.seed("client_payroll_settings", {"id": "cps", "firm_id": _REL_FIRM, "client_id": _REL_CLIENT, "payroll_enabled": True})
    for name in ("Salaries Expense", "Net Salary Payable", "PF Payable", "ESI Payable", "PT Payable", "TDS Payable - Salary"):
        d.seed("chart_of_accounts", {"firm_id": _REL_FIRM, "client_id": _REL_CLIENT, "account_name": name, "is_active": True})
    for emp_id, name in (("e-a", "Asha"), ("e-b", "Bala")):
        d.seed("payroll_employees", {
            "id": emp_id, "firm_id": _REL_FIRM, "client_id": _REL_CLIENT, "name": name, "basic_paise": 5_000_000,
            "hra_percent": 0.0, "da_percent": 0.0, "other_allowances_paise": 0, "lta_paise": 0, "medical_paise": 0,
            "special_allowance_paise": 0, "pf_applicable": False, "esi_applicable": False, "pt_applicable": False,
            "is_active": True, "status": "active", "joining_date": "2020-04-01"})
        for month in (9, 10):
            d.seed("attendance", {"firm_id": _REL_FIRM, "employee_id": emp_id, "month": month, "year": 2026,
                                  "working_days": 26, "days_present": 26, "casual_leaves": 0, "sick_leaves": 0,
                                  "earned_leaves": 0, "lop_days": 0})
    # Asha's position holds April to September; Bala has none.
    d.seed("payroll_opening_positions", {
        "firm_id": _REL_FIRM, "client_id": _REL_CLIENT, "employee_id": "e-a", "financial_year": "2026-27",
        "first_month_here": "2026-10-01", "months_paid": 6, "gross_paise": 30_000_000, "tds_paise": 600_000,
        "esi_contributed_earlier_in_period": None})
    return d


def _rel_run(month):
    out = P.create_run(P.PayrollRunIn(client_id=_REL_CLIENT, month=month), _REL_CALLER)
    assert out["success"] is True
    return out["data"]["id"]


def test_a_month_inside_an_opening_position_is_not_released(rel_db):
    """September is inside Asha's position (April to September). Releasing a September slip for her here would count that
    month twice in every later spread, the projection and a settlement, which is what the PUT refuses the other way round."""
    from fastapi import HTTPException
    run_id = _rel_run("2026-09")
    with pytest.raises(HTTPException) as e:
        P.finalize_run(run_id, _REL_CALLER)
    assert e.value.status_code == 409
    assert "Asha" in e.value.detail and "Bala" not in e.value.detail and "counted" in e.value.detail
    run = next(r for r in rel_db.rows("payroll_runs") if r["id"] == run_id)
    assert run["status"] == "draft" and not run.get("journal_entry_id"), "refused before the journal"


def test_the_first_month_of_the_position_and_after_are_released(rel_db):
    out = P.finalize_run(_rel_run("2026-10"), _REL_CALLER)
    assert out["success"] is True and out["data"]["status"] == "finalized"


# ── the projection: a month before the product ran is not a paid nil ─────────────────

def test_a_projected_month_inside_the_opening_position_carries_no_figure_of_its_own(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from core.auth import get_current_user
    from tests.e2e_harness import FakeDB
    db = FakeDB()
    monkeypatch.setattr(P, "_db", lambda: db)
    app = FastAPI()
    app.include_router(P.router)
    app.dependency_overrides[get_current_user] = lambda: {"id": "u1", "firm_id": "F1", "role": "Partner", "email": "p@f1.test"}
    db.seed("payroll_employees", {**_SLIP_EMP, "firm_id": "F1", "client_id": "C1", "status": "active"})
    db.seed("payroll_opening_positions", {"firm_id": "F1", "client_id": "C1", "employee_id": EMP, "financial_year": "2026-27",
                                          "first_month_here": "2026-10-01", "months_paid": 6, "gross_paise": 6_000_000,
                                          "tds_paise": 120_000})
    d = TestClient(app).get("/api/payroll/tds-projection",
                            params={"client_id": "C1", "employee_id": EMP, "financial_year": "2026-27"}).json()["data"]
    before = [m for m in d["months"] if m["month"] < "2026-10"]
    assert len(before) == 6 and all(m["opening"] and m["actual"] for m in before)
    assert all(m["gross_paise"] is None and m["tds_paise"] is None for m in before), "unknown, never a paid zero"
    after = [m for m in d["months"] if m["month"] >= "2026-10"]
    assert all(not m["opening"] and not m["actual"] and m["gross_paise"] is not None for m in after)
    assert d["deducted_so_far_paise"] == 120_000 and d["months_paid"] == 6
    assert d["opening_position"] == {"first_month_here": "2026-10", "months_paid": 6, "gross_paise": 6_000_000,
                                     "tds_paise": 120_000}
    assert d["estimated_annual_gross_paise"] == 6_000_000 + sum(m["gross_paise"] for m in after)
