"""`/statutory-position` reads the MONTH'S OWN RUN, when one exists.

WHAT WAS WRONG

    Confirmed by live browser testing: an employee with a single day of LOP
    (loss of pay) in September showed a FULL month's gross (₹1,25,000) on the
    Statutory Deductions screen, while the real September payroll run — even
    a draft one — correctly deducted on the LOP-adjusted figure
    (₹1,20,192.30). `statutory_position` read `payroll_employees` and
    `_pay_in_force` (which resolves WHICH salary revision governs the month,
    never how many days of it were actually worked) and re-projected a clean
    full month from scratch, ignoring that the run itself had already
    computed — and stored, on `payroll_slips` — the real, attendance-adjusted
    figures for that very employee and month.

    PAY-04's rule ("a draft has deducted nothing") is about crediting
    withholding/contribution HISTORY that has not happened — it is not a
    reason to prefer a WORSE-informed number over a BETTER-informed one for
    what a specific month's figures actually are. A draft run's slip is more
    accurate than a projection, not less, because it has real attendance
    behind it; this file's tests hold that a draft run's slip is read exactly
    like a finalised one's.

THE FIX

    `statutory_position` now looks up the client's payroll_runs row for that
    (firm, client, month) and, per employee, prefers that run's own
    payroll_slips row when one exists — reading gross/basic/da/PF/ESI/wage-base
    figures straight off the slip rather than recomputing them. An employee
    with no slip in that run (e.g. hired after the run was created) still
    falls back to the projection, which is the docstring's own "people no run
    has covered yet" case and is unchanged.
"""
from __future__ import annotations

from datetime import date

import pytest

import routers.payroll as pr
from tests.test_payroll_reports_what_it_deducted import _DB, USER, FIRM, CLIENT

MONTH = "2026-09"
FY = "2026-27"

EMPLOYEE = dict(id="e1", client_id=CLIENT, firm_id=FIRM, name="Priya Rao",
                status="active", basic_paise=1_00_000_00, hra_percent=25,
                da_percent=0, lta_paise=0, medical_paise=0,
                special_allowance_paise=0, other_allowances_paise=0,
                pf_applicable=True, eps_eligible=True,
                esi_applicable=False, pt_applicable=False,
                joining_date="2018-04-01", gratuity_act_covered=True)

# A real September run's slip for this employee: one day of LOP moved gross
# from a clean ₹1,25,000 to ₹1,20,192.30 and PF moved with it. These figures
# stand in for "whatever the run actually computed" — the test does not care
# whether they are independently re-derivable, only that the screen reads
# them rather than recomputing a different answer.
SEPTEMBER_SLIP = dict(
    employee_id="e1", run_id="run-1",
    basic_paise=96_153_85, da_paise=0, gross_paise=1_20_192_30,
    pf_employee_paise=11_538_00, pf_employer_paise=11_538_00,
    pf_employer_eps_paise=1_250_00, pf_employer_epf_paise=10_288_00,
    edli_paise=577_00, pf_admin_paise=115_00,
    esi_employee_paise=0, esi_employer_paise=0,
    pf_wages_paise=96_153_85, pf_wages_addback_paise=0,
    pf_wages_rule_applied=False,
    net_paise=1_08_654_30, working_days=30, days_present=29, lop_days=1,
)

FULL_MONTH_GROSS_PAISE = 1_25_000_00   # basic + 25% HRA, no LOP


def _db_with_run(slip: dict | None, run_status: str = "draft") -> _DB:
    runs = [{"id": "run-1", "firm_id": FIRM, "client_id": CLIENT,
             "month": MONTH, "status": run_status}]
    slips = [slip] if slip else []
    return _DB({"payroll_employees": [EMPLOYEE], "payroll_runs": runs,
                "payroll_slips": slips})


def _rows(db, monkeypatch, month=MONTH):
    monkeypatch.setattr(pr, "_db", lambda: db)
    resp = pr.statutory_position(client_id=CLIENT, month=month, current_user=USER)
    assert resp["success"] is True
    return resp["data"]["rows"]


def test_a_draft_runs_own_slip_is_read_over_the_projection(monkeypatch):
    """This is the bug. A projection from the master would answer
    FULL_MONTH_GROSS_PAISE; the run's own (draft) slip must win instead."""
    db = _db_with_run(SEPTEMBER_SLIP, run_status="draft")
    row = _rows(db, monkeypatch)[0]
    assert row["gross_paise"] == SEPTEMBER_SLIP["gross_paise"]
    assert row["gross_paise"] != FULL_MONTH_GROSS_PAISE
    assert row["pf_employee_paise"] == SEPTEMBER_SLIP["pf_employee_paise"]
    assert row["pf_employer_paise"] == SEPTEMBER_SLIP["pf_employer_paise"]
    assert row["pf_employer_eps_paise"] == SEPTEMBER_SLIP["pf_employer_eps_paise"]
    assert row["pf_employer_epf_paise"] == SEPTEMBER_SLIP["pf_employer_epf_paise"]
    assert row["edli_paise"] == SEPTEMBER_SLIP["edli_paise"]
    assert row["pf_admin_paise"] == SEPTEMBER_SLIP["pf_admin_paise"]
    assert row["basic_paise"] == SEPTEMBER_SLIP["basic_paise"]
    assert row["pf_wages_paise"] == SEPTEMBER_SLIP["pf_wages_paise"]


@pytest.mark.parametrize("status", ["draft", "review", "finalized", "paid"])
def test_every_run_status_is_read_the_same_way(status, monkeypatch):
    """Draft, review, finalized or paid all carry the same _compute_slip
    output — none of them is preferred or excluded over another here."""
    db = _db_with_run(SEPTEMBER_SLIP, run_status=status)
    row = _rows(db, monkeypatch)[0]
    assert row["gross_paise"] == SEPTEMBER_SLIP["gross_paise"]


def test_an_employee_with_no_slip_in_the_run_still_falls_back_to_projection(monkeypatch):
    """A run exists for the client+month, but this particular employee has no
    slip in it (e.g. hired after the run was created) — the docstring's own
    'people no run has covered yet' case, unchanged by this fix."""
    db = _db_with_run(slip=None)
    row = _rows(db, monkeypatch)[0]
    assert row["gross_paise"] == FULL_MONTH_GROSS_PAISE


def test_no_run_at_all_still_projects_from_the_master(monkeypatch):
    """The ordinary case for a client who has not yet run this month's
    payroll — must keep working exactly as before."""
    db = _DB({"payroll_employees": [EMPLOYEE], "payroll_runs": [], "payroll_slips": []})
    row = _rows(db, monkeypatch)[0]
    assert row["gross_paise"] == FULL_MONTH_GROSS_PAISE


def test_a_run_in_a_different_month_is_not_matched(monkeypatch):
    """The lookup is scoped to THIS month — an August run's slip must never
    answer a September position."""
    runs = [{"id": "run-0", "firm_id": FIRM, "client_id": CLIENT,
             "month": "2026-08", "status": "finalized"}]
    slips = [{**SEPTEMBER_SLIP, "run_id": "run-0"}]
    db = _DB({"payroll_employees": [EMPLOYEE], "payroll_runs": runs, "payroll_slips": slips})
    row = _rows(db, monkeypatch)[0]
    assert row["gross_paise"] == FULL_MONTH_GROSS_PAISE


# ── gratuity_years must floor, matching its own reason sentence ─────────────
#
# A separate but adjacent defect on the same response: `gratuity_years` read
# `service_years_counted` (§4(2)'s "part thereof in excess of six months"
# rounding, correct ONLY inside the payable-amount formula once eligible) where
# every other figure on the row — and the reason sentence itself — uses
# `completed_years`, the plain §4(1) floor. An employee at 4 years 9 months is
# excluded (years < 5) and the reason correctly says "4 completed years", while
# gratuity_years showed 5 — the screen and its own tooltip disagreeing about
# the same employee.

NEARLY_FIVE_YEARS = dict(EMPLOYEE, id="e2",
                         joining_date="2021-12-01")   # 4y9m by 2026-09-30


def test_gratuity_years_floors_like_the_reason_sentence_does(monkeypatch):
    db = _DB({"payroll_employees": [NEARLY_FIVE_YEARS], "payroll_runs": [], "payroll_slips": []})
    row = _rows(db, monkeypatch)[0]
    assert row["gratuity_eligible"] is False
    assert row["gratuity_years"] == 4
    assert "4 completed year" in row["gratuity_reasons"][0]
    # The bug: service_years_counted rounds this same employee up to 5 for the
    # (unreachable, since ineligible) payable formula. gratuity_years must not
    # read that number.
    grat = pr.gratuity_domain.compute(
        basic_plus_da_paise=NEARLY_FIVE_YEARS["basic_paise"],
        joining=date(2021, 12, 1), leaving=date(2026, 9, 30), covered_by_the_act=True)
    assert grat.service_years_counted == 5, "fixture no longer exercises the rounding case"
    assert row["gratuity_years"] != grat.service_years_counted


def test_gratuity_years_still_reports_the_floor_once_eligible(monkeypatch):
    """Past five years the same rule applies — completed_years, never the
    counted-for-the-formula figure, however the two compare."""
    veteran = dict(EMPLOYEE, id="e3", joining_date="2015-12-01")  # 10y9m
    db = _DB({"payroll_employees": [veteran], "payroll_runs": [], "payroll_slips": []})
    row = _rows(db, monkeypatch)[0]
    assert row["gratuity_eligible"] is True
    assert row["gratuity_years"] == 10
