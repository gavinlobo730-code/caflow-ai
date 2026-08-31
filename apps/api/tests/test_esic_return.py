"""
The ESIC monthly contribution return, and ESI Rule 50.

TWO THINGS HERE, AND THE SECOND IS A BUG FIX

The file: six columns per insured person — IP NUMBER, IP NAME, NO OF DAYS,
TOTAL MONTHLY WAGES, REASON CODE, LAST WORKING DAY.

The rule: _compute_esi used to return zero the moment gross exceeded ₹21,000.
ESI Rule 50 says an employee whose wages rise above the ceiling PART WAY THROUGH
a contribution period (April-September, October-March) remains an employee until
that period ends. Someone on ₹20,500 in April raised to ₹24,000 in May
contributes on the full ₹24,000 every month to September. Dropping them in May
under-deducts for five months, and the employer carries the shortfall with
interest.

WHAT THE FILE DELIBERATELY WILL NOT DO

Invent a reason code. It explains why an insured person had zero working days —
left service, on leave, out of coverage — and this system does not record why
somebody was unpaid; nor could the numeric coding be confirmed against an
authoritative ESIC source. A wrong code is a false statement about an employee's
service on a filed return, so a zero-wage member is a PROBLEM for the CA to
resolve and the file is withheld.
"""
from __future__ import annotations

import pytest

from domain.payroll.esic import build_esic_return, NOT_APPLICABLE
from domain.payroll.statutory import esi_contribution_period
from routers.payroll import _compute_esi, _compute_slip


def _slip(**over) -> dict:
    base = dict(employee_id="e1", gross_paise=20_500_00, lop_days=0,
                esi_employee_paise=153_75, esi_employer_paise=666_25)
    base.update(over)
    return base


def _emp(**over) -> dict:
    base = dict(id="e1", name="Ravi Kumar", esi_number="1234567890",
                esi_applicable=True)
    base.update(over)
    return base


def _build(slips=None, emps=None, days=30):
    slips = slips or [_slip()]
    emps = emps or [_emp()]
    return build_esic_return(slips=slips,
                             employees_by_id={e["id"]: e for e in emps},
                             days_in_month=days)


# ── the file ─────────────────────────────────────────────────────────────────

def test_the_row_carries_the_six_columns():
    r = _build()
    assert r.problems == []
    header, row = r.to_csv().splitlines()
    assert header.split(",") == ["IP Number", "IP Name", "No of Days",
                                 "Total Monthly Wages", "Reason Code",
                                 "Last Working Day"]
    assert row == f"1234567890,RAVI KUMAR,30,20500,{NOT_APPLICABLE},"


def test_days_are_the_month_less_unpaid_days():
    assert _build([_slip(lop_days=4)], days=30).members[0].days == 26


def test_a_name_with_a_comma_cannot_split_the_row():
    """The CSV equivalent of the ECR's delimiter bug: an unquoted comma shifts
    every column after the name."""
    r = _build(emps=[_emp(name="Ravi, Kumar")])
    row = r.to_csv().splitlines()[1]
    assert row.startswith('1234567890,"RAVI, KUMAR",30,')
    assert len(next(__import__("csv").reader([row]))) == 6


@pytest.mark.parametrize("bad", ["", "12345", "12345678901", "123456789A"])
def test_a_bad_insurance_number_is_refused_by_name(bad):
    r = _build(emps=[_emp(esi_number=bad)])
    assert r.members == []
    assert any("Ravi Kumar" in p for p in r.problems), r.problems
    assert not r.is_filable


def test_a_member_with_no_wages_is_a_problem_not_a_guessed_reason_code():
    """The refusal this module exists to make. ESIC wants a reason code and this
    system does not know the reason — so it asks rather than inventing one."""
    r = _build([_slip(gross_paise=0, lop_days=30)], days=30)
    assert r.members == []
    assert any("reason code" in p for p in r.problems), r.problems
    assert not r.is_filable


def test_an_employee_outside_the_scheme_is_left_off():
    r = _build([_slip(esi_employee_paise=0, esi_employer_paise=0)],
               [_emp(esi_applicable=False)])
    assert r.members == [] and r.problems == []


def test_more_unpaid_days_than_the_month_has_is_refused():
    r = _build([_slip(lop_days=31)], days=30)
    assert r.members == []
    assert any("31 unpaid days in a 30-day month" in p for p in r.problems)


# ── Rule 50 ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("month,period", [
    ("2026-04", "2026-H1"), ("2026-09", "2026-H1"),
    ("2026-10", "2026-H2"), ("2027-03", "2026-H2"),
    ("2027-04", "2027-H1"),
])
def test_contribution_periods_run_april_to_september_and_october_to_march(month, period):
    """October to March is ONE period spanning a calendar year boundary, not
    two — which is why the label carries the year the period started."""
    assert esi_contribution_period(month) == period


def test_below_the_ceiling_contributes_normally():
    got = _compute_esi(20_500_00)
    assert got["employee"] == 153_75          # 0.75%
    assert got["employer"] == 666_25          # 3.25%


def test_a_new_joiner_above_the_ceiling_is_outside_the_scheme():
    """Rule 50's continuation is for someone who WAS covered. Somebody who
    starts above the ceiling never was."""
    assert _compute_esi(24_000_00) == {"employee": 0, "employer": 0}


def test_crossing_the_ceiling_mid_period_does_not_end_coverage():
    """The bug. ₹20,500 in April, raised to ₹24,000 in May: contribution
    continues on the FULL ₹24,000 until September."""
    got = _compute_esi(24_000_00, covered_at_period_start=True)
    assert got["employee"] == 180_00
    assert got["employer"] == 780_00


def test_contribution_is_on_the_whole_wage_with_no_cap():
    """₹21,000 is an eligibility threshold, not a ceiling on the amount — a
    covered member contributes on everything they earn."""
    got = _compute_esi(50_000_00, covered_at_period_start=True)
    assert got["employee"] == 375_00           # 0.75% of 50,000
    assert got["employer"] == 1_625_00         # 3.25% of 50,000


def test_the_slip_honours_the_rule():
    emp = dict(basic_paise=24_000_00, da_percent=0, hra_percent=0,
               pf_applicable=False, esi_applicable=True, pt_applicable=False)
    assert _compute_slip(emp)["esi_employee_paise"] == 0
    assert _compute_slip(emp, esi_covered_at_period_start=True)["esi_employee_paise"] == 180_00
