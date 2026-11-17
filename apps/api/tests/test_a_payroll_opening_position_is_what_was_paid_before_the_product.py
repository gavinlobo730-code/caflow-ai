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


def test_the_spread_runs_over_the_months_that_remain_once_the_position_is_counted():
    """The point of the item: with six months behind it the year's tax is spread over six, not twelve."""
    outstanding = 600_000 - 120_000
    assert outstanding // P._months_remaining_for_spread(6) == 80_000
    assert outstanding // P._months_remaining_for_spread(0) == 40_000      # what the run did before: as if nothing had been paid


def test_a_failed_position_read_leaves_the_ytd_as_it_was_and_does_not_fail_the_run():
    class Boom(_DB):
        def table(self, n):
            if n == "payroll_opening_positions":
                raise RuntimeError("down")
            return super().table(n)
    db = Boom(payroll_runs=[], payroll_slips=[])
    assert P._tds_already_deducted_this_fy(db, FIRM, CLIENT, "2026-10", "2026-27") == {}


def test_esi_coverage_counts_an_explicit_yes_in_the_same_contribution_period_and_never_an_unknown():
    yes = position(esi_contributed_earlier_in_period=True)
    unknown = position(esi_contributed_earlier_in_period=None, employee_id="e2")
    db = _DB(payroll_runs=[], payroll_slips=[], payroll_opening_positions=[yes, unknown])
    # ESI periods are Apr-Sep and Oct-Mar: a position starting in October covers a November run, not a run before October.
    assert P._members_contributing_earlier_this_period(db, FIRM, CLIENT, "2026-11") == {EMP}
    assert P._members_contributing_earlier_this_period(db, FIRM, CLIENT, "2026-09") == set()


# ── the gap ───────────────────────────────────────────────────────────────────

def test_an_employee_with_no_earlier_month_and_no_position_is_named():
    gap = P._opening_position_gap({"id": EMP, "name": "Asha", "joining_date": "2020-01-01"}, "2026-10", "2026-27", {})
    assert len(gap) == 1 and "Asha" in gap[0] and "opening position" in gap[0]


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
