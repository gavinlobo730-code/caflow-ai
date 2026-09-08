"""Three payroll defects that all have the same shape: a second implementation.

Every one of these is a place where payroll computed a figure twice, or
projected a year that is not the year it pays, and nothing on the screen looked
wrong:

  * `/statutory-position` projected PF on `basic + DA` — the rule that stopped
    being right when the four Labour Codes commenced on 21-11-2025 — while the
    payroll run deducted on the Code on Wages §2(y) base. The same employee had
    two PF figures, and only one of them reached a challan.

  * §192's projection was months-employed aware for SALARY and not for the
    reliefs against it: §10(13A) HRA and §16(iii) professional tax were both
    this month's amount times twelve, for an employee the same computation knew
    was paid for six months.

  * `/employee-exceptions` called `logger` inside its `except` block, and the
    module defines `_logger`. The handler was there to degrade gracefully on a
    read failure and instead raised NameError from inside itself — a 500 on the
    first real failure, and only on a real failure.
"""
from __future__ import annotations

from datetime import date

import pytest

import routers.payroll as pr
from domain.payroll import declarations as decl_domain

FIRM = "firm-1"
CLIENT = "client-1"
USER = {"id": "u1", "firm_id": FIRM, "role": "partner"}


# ── a fake PostgREST, only as much of one as these three endpoints use ───────

class _Q:
    def __init__(self, rows, raise_for):
        self.rows, self._raise = list(rows), raise_for

    def select(self, *_a, **_k):
        if self._raise:
            raise RuntimeError("PostgREST said no")
        return self

    def eq(self, k, v):
        self.rows = [r for r in self.rows if str(r.get(k)) == str(v)]
        return self

    def in_(self, k, vals):
        vals = {str(v) for v in vals}
        self.rows = [r for r in self.rows if str(r.get(k)) in vals]
        return self

    def order(self, *_a, **_k):
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def execute(self):
        return type("R", (), {"data": [dict(r) for r in self.rows]})()


class _DB:
    def __init__(self, tables: dict, raise_on: str | None = None):
        self.tables, self.raise_on = tables, raise_on

    def table(self, name):
        return _Q(self.tables.get(name, []), raise_for=(name == self.raise_on))


@pytest.fixture(autouse=True)
def _allow_every_client(monkeypatch):
    monkeypatch.setattr(pr, "assert_client_access", lambda *a, **k: None)


# ═════════════════════════════════════════════════════════════════════════════
# ONE PF WAGE BASE — /statutory-position must agree with the run
# ═════════════════════════════════════════════════════════════════════════════
#
# ₹10,000 basic with ₹18,000 of HRA is the ordinary low-basic Indian structure
# at exactly the salary level the ₹15,000 ceiling does not bail out. Exclusions
# are 64% of total remuneration, the excess over half is deemed wages, and the
# base is ₹14,000 — so employee PF is ₹1,680. Projecting `basic + DA` showed
# ₹1,200 for the same person in the same month.

LOW_BASIC = dict(id="e1", client_id=CLIENT, firm_id=FIRM, name="Asha Kumar",
                 status="active", basic_paise=10_000_00, hra_percent=180,
                 da_percent=0, lta_paise=0, medical_paise=0,
                 special_allowance_paise=0, other_allowances_paise=0,
                 pf_applicable=True, eps_eligible=True,
                 esi_applicable=False, pt_applicable=False,
                 joining_date="2015-04-01", gratuity_act_covered=True)


def _position_rows(emp: dict, month: str, monkeypatch) -> list[dict]:
    db = _DB({"payroll_employees": [emp], "payroll_runs": [], "payroll_slips": []})
    monkeypatch.setattr(pr, "_db", lambda: db)
    resp = pr.statutory_position(client_id=CLIENT, month=month, current_user=USER)
    assert resp["success"] is True
    return resp["data"]["rows"]


@pytest.mark.parametrize("month,fy,pf_month", [("2026-12", "2026-27", 12),
                                               ("2025-10", "2025-26", 10)])
def test_the_projection_and_the_run_produce_the_same_pf(month, fy, pf_month,
                                                        monkeypatch):
    """A parity test, in the shape this repo already uses for cash flow and the
    Schedule III ageing: every field of the split, on both sides of the Labour
    Codes' commencement, through the two code paths that used to disagree."""
    slip = pr._compute_slip(LOW_BASIC, fy=fy, pt_month=pf_month)
    row = _position_rows(LOW_BASIC, month, monkeypatch)[0]

    for field in ("pf_employee_paise", "pf_employer_paise",
                  "pf_employer_eps_paise", "pf_employer_epf_paise",
                  "edli_paise", "pf_wages_paise", "pf_wages_addback_paise",
                  "pf_wages_rule_applied"):
        assert row[field] == slip[field], field


def test_the_governed_month_is_the_higher_figure_on_both_paths(monkeypatch):
    """The parity above would also pass if BOTH were wrong. This pins the
    number: 12% of the ₹14,000 §2(y) base, not of ₹10,000 of basic."""
    row = _position_rows(LOW_BASIC, "2026-12", monkeypatch)[0]
    assert row["pf_employee_paise"] == 1_680_00      # not ₹1,200 on basic alone
    assert row["pf_employer_paise"] == 1_680_00      # both sides were short
    assert row["pf_wages_paise"] == 14_000_00
    assert row["pf_wages_addback_paise"] == 4_000_00
    assert row["pf_wages_rule_applied"] is True


def test_a_month_before_commencement_still_projects_the_old_base(monkeypatch):
    """October 2025 is EPF Act §6. The correction must not restate a month the
    §2(y) definition does not reach."""
    row = _position_rows(LOW_BASIC, "2025-10", monkeypatch)[0]
    assert row["pf_wages_paise"] == 10_000_00
    assert row["pf_wages_rule_applied"] is False
    assert row["pf_employee_paise"] == 1_200_00


def test_gratuity_is_deliberately_left_on_basic_plus_da(monkeypatch):
    """The Code redefines "wages" for gratuity too, and CLAUDE.md records that
    as unverified and deliberately not changed. Pinned here so a later change
    is a decision rather than something that rides along with the PF base."""
    row = _position_rows(LOW_BASIC, "2026-12", monkeypatch)[0]
    expected = pr.gratuity_domain.compute(
        basic_plus_da_paise=10_000_00,
        joining=date(2015, 4, 1), leaving=date(2026, 12, 31),
        covered_by_the_act=True).payable_paise
    assert row["gratuity_payable_paise"] == expected


# ═════════════════════════════════════════════════════════════════════════════
# §192 PROJECTS THE YEAR THE EMPLOYEE IS ACTUALLY PAID FOR
# ═════════════════════════════════════════════════════════════════════════════
#
# §192(1) charges tax on "the estimated income of the assessee under the head
# Salaries" for that financial year, and _months_employed_in_fy already makes
# the SALARY six months for an October joiner. The reliefs against that salary
# have to be estimated over the same six months:
#
#   * §10(13A) with Rule 2A is the least of the HRA received, 50%/40% of
#     salary, and rent paid less 10% of salary — all for "the period during
#     which the accommodation was occupied". A twelve-month salary doubles the
#     10% subtracted from rent and can erase the third limb entirely.
#   * §16(iii) professional tax is deductible as ACTUALLY PAID.

OCTOBER_JOINER = dict(basic_paise=1_00_000_00, hra_percent=50, da_percent=0,
                      pf_applicable=False, esi_applicable=False,
                      pt_applicable=False, joining_date="2026-10-01")


def _metro_renter(monthly_rent_paise: int, months: int):
    """An old-regime employee who proved metro rent for the months they were
    here. §10(13A) is the only relief in play, so nothing else moves the tax."""
    annual_rent = monthly_rent_paise * months
    return decl_domain.Declaration(
        employee_id="e1", fy="2026-27", regime=decl_domain.REGIME_OLD,
        status=decl_domain.STATUS_VERIFIED, proofs_verified=True,
        rent_paid_declared_paise=annual_rent,
        rent_paid_verified_paise=annual_rent, rent_is_metro=True)


def _annual_tax_for(months_employed: int) -> int:
    """The year's tax the run is withholding towards.

    _months_remaining_for_spread deliberately counts what THIS employer has
    already paid, so with nothing paid yet the month's deduction is exactly a
    twelfth of the year's tax — see its docstring for why that is not the
    calendar.
    """
    slip = pr._compute_slip(
        OCTOBER_JOINER, fy="2026-27", pt_month=10,
        declaration=_metro_renter(20_000_00, months_employed),
        months_employed_in_fy=months_employed)
    return slip["tds_paise"] * 12


def test_an_october_joiners_hra_is_annualised_over_the_months_they_work():
    """Six months of ₹1,00,000 basic and ₹50,000 HRA against ₹20,000 a month of
    metro rent. Treating the salary and the HRA as twelve months' worth costs
    the employee ₹12,480 of tax across the half-year they are employed."""
    assert pr._months_employed_in_fy("2026-10-01", "2026-27") == 6
    assert _annual_tax_for(6) == 73_320_00


def test_a_whole_year_employee_is_completely_unaffected():
    """months_employed_in_fy is 12 for anyone employed from 1 April, and an
    unknown joining date also returns 12 — so the overwhelmingly common case
    computes exactly as it did."""
    assert pr._months_employed_in_fy("2020-04-01", "2026-27") == 12
    assert pr._months_employed_in_fy(None, "2026-27") == 12


def test_professional_tax_is_annualised_the_same_way():
    """§16(iii) allows what was actually paid. The state slabs are monthly, so
    a six-month employee pays six months of it."""
    emp = dict(OCTOBER_JOINER, pt_applicable=True, pt_state="MH")
    captured = {}

    def _spy(**kwargs):
        captured.update(kwargs)
        return 0

    original = pr._monthly_tds
    try:
        pr._monthly_tds = _spy                        # type: ignore[assignment]
        slip = pr._compute_slip(emp, fy="2026-27", pt_month=10,
                                months_employed_in_fy=6)
    finally:
        pr._monthly_tds = original                    # type: ignore[assignment]

    assert slip["pt_paise"] > 0
    assert captured["professional_tax_paise"] == slip["pt_paise"] * 6
    assert captured["hra_received_paise"] == slip["hra_paise"] * 6
    assert captured["basic_plus_da_paise"] == (
        slip["basic_paise"] + slip["da_paise"]) * 6


def test_someone_whose_joining_date_falls_after_this_year_gets_no_relief():
    """months_employed_in_fy is 0 there, the projected salary is nothing, and a
    relief against nothing is nothing — not a negative multiplier."""
    assert pr._months_employed_in_fy("2027-06-01", "2026-27") == 0
    slip = pr._compute_slip(OCTOBER_JOINER, fy="2026-27", pt_month=10,
                            declaration=_metro_renter(20_000_00, 6),
                            months_employed_in_fy=0)
    assert slip["tds_paise"] == 0


# ═════════════════════════════════════════════════════════════════════════════
# THE EXCEPTION INDEX DEGRADES INSTEAD OF RAISING
# ═════════════════════════════════════════════════════════════════════════════

EXCEPTION_TABLES = {
    "client_payroll_settings": [{"client_id": CLIENT, "firm_id": FIRM,
                                 "payroll_enabled": True}],
    "payroll_employees": [dict(id="e1", client_id=CLIENT, firm_id=FIRM,
                               name="Asha Kumar", pan="", uan="",
                               esi_number="", date_of_birth=None,
                               bank_account_no="", bank_ifsc="",
                               pf_applicable=True, esi_applicable=True,
                               pt_applicable=False, pt_state=None,
                               status="active")],
    "clients": [{"id": CLIENT, "firm_id": FIRM, "client_name": "Acme Pvt Ltd"}],
    "payroll_it_declarations": [],
}


def test_a_declarations_read_failure_does_not_become_a_500(monkeypatch):
    """The `except` block exists so a declarations table that cannot be read
    costs the CA the old-regime refinement and nothing else. Calling an
    undefined name inside it turned the graceful path into the only path that
    fails — and only on a real failure, which is why it survived."""
    db = _DB(EXCEPTION_TABLES, raise_on="payroll_it_declarations")
    monkeypatch.setattr(pr, "_db", lambda: db)

    resp = pr.payroll_employee_exceptions(financial_year="2026-27",
                                          current_user=USER)

    assert resp["success"] is True
    assert resp["data"]["employees_checked"] == 1
    # The index still does its job: this employee has no UAN and no PAN.
    assert resp["data"]["exceptions"], "the index must still report the gaps"


def test_the_same_call_succeeds_when_the_table_reads_normally(monkeypatch):
    """The control: nothing about the fix depends on the read failing."""
    monkeypatch.setattr(pr, "_db", lambda: _DB(EXCEPTION_TABLES))
    resp = pr.payroll_employee_exceptions(financial_year="2026-27",
                                          current_user=USER)
    assert resp["success"] is True
    assert resp["data"]["employees_checked"] == 1


# ═════════════════════════════════════════════════════════════════════════════
# THE 24Q ENDPOINT HANDS THE BUILDER BOTH §16(ia) FIGURES
# ═════════════════════════════════════════════════════════════════════════════

def test_the_annexure_endpoint_passes_both_standard_deductions(monkeypatch):
    """domain/payroll/annexure2.py selects per row on the regime, which it can
    only do if the route supplies both. ₹75,000 is the new regime's figure and
    ₹50,000 the old one; they are not interchangeable."""
    from domain.income_tax.statutory_rates import rates_for

    captured: dict = {}
    real = pr.build_annexure_ii

    def _spy(**kwargs):
        captured.update(kwargs)
        return real(**kwargs)

    monkeypatch.setattr(pr, "_db", lambda: _DB({}))
    monkeypatch.setattr(pr, "build_annexure_ii", _spy)

    pr.form_24q_annexure_ii(client_id=CLIENT, financial_year="2026-27",
                            current_user=USER)

    rates = rates_for("2026-27")
    assert captured["standard_deduction_paise"] == \
        rates.new_regime_standard_deduction_paise
    assert captured["old_regime_standard_deduction_paise"] == \
        rates.old_regime_standard_deduction_paise
    assert (captured["standard_deduction_paise"]
            != captured["old_regime_standard_deduction_paise"])
