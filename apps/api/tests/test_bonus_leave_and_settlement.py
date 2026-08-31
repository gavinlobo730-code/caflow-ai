"""
Statutory bonus (Payment of Bonus Act 1965), leave encashment (IT Act
§10(10AA)) and the full and final settlement that composes them.

Figures worked from the statutes by hand.
"""
from datetime import date

import pytest

from domain.payroll import bonus as B
from domain.payroll import gratuity as G
from domain.payroll import leave_encashment as L
from domain.payroll import settlement as S


def _bonus(**kw):
    kw.setdefault("accounting_year", "2025-26")
    kw.setdefault("monthly_salary_paise", 18_000 * 100)
    kw.setdefault("months_worked", 12)
    kw.setdefault("working_days_in_year", 250)
    return B.compute(**kw)


# ── Payment of Bonus Act 1965 ────────────────────────────────────────────────

def test_the_21000_ceiling_puts_someone_outside_the_act(): 
    """§2(13): an employee is one drawing salary NOT EXCEEDING ₹21,000 a month.
    Above it the Act does not apply — an ex gratia is not statutory bonus."""
    r = _bonus(monthly_salary_paise=25_000 * 100)
    assert not r.eligible
    assert r.payable_paise == 0
    assert any("§2(13)" in x for x in r.reasons)

    assert _bonus(monthly_salary_paise=21_000 * 100).eligible


def test_bonus_is_computed_on_7000_when_no_minimum_wage_is_known():
    """§12's calculation ceiling. 8.33% of ₹7,000 × 12 = ₹6,997.20."""
    r = _bonus()
    assert r.calculation_base_monthly_paise == 7_000 * 100
    assert r.payable_paise == 7_000 * 100 * 12 * 833 // 10000
    assert r.payable_paise == 6_997_20


def test_a_higher_minimum_wage_raises_the_calculation_base():
    """§12 says ₹7,000 'or the minimum wage for the scheduled employment ...
    WHICHEVER IS HIGHER'. Treating ₹7,000 as the ceiling underpays — here by
    more than half."""
    r = _bonus(minimum_wage_monthly_paise=11_000 * 100)
    assert r.calculation_base_monthly_paise == 11_000 * 100
    assert r.payable_paise == 10_995_60
    assert r.payable_paise > _bonus().payable_paise * 1.5


def test_a_minimum_wage_below_7000_does_not_lower_the_base():
    r = _bonus(minimum_wage_monthly_paise=5_000 * 100)
    assert r.calculation_base_monthly_paise == 7_000 * 100


def test_the_base_never_exceeds_the_salary_actually_drawn():
    """§12 caps the base; it does not invent salary the employee never had."""
    r = _bonus(monthly_salary_paise=6_000 * 100)
    assert r.calculation_base_monthly_paise == 6_000 * 100


def test_an_unknown_minimum_wage_is_reported_not_assumed_away():
    assert any("WHICHEVER IS HIGHER" in g for g in _bonus().gaps)
    assert not _bonus(minimum_wage_monthly_paise=11_000 * 100).gaps


def test_thirty_working_days_is_the_eligibility_test():
    """§8 — thirty WORKING days, not thirty calendar days and not a proportion
    of the year."""
    assert not _bonus(working_days_in_year=29).eligible
    assert _bonus(working_days_in_year=30).eligible


def test_the_minimum_is_payable_whether_or_not_there_is_a_surplus():
    """§10: 8.33% 'whether or not the employer has any allocable surplus'."""
    r = _bonus(rate_bps=0)
    assert r.payable_paise == r.minimum_paise
    assert r.payable_paise > 0


def test_bonus_is_capped_at_twenty_percent():
    """§11."""
    r = _bonus(rate_bps=5000)
    assert r.payable_paise == r.maximum_paise
    assert r.payable_paise == 7_000 * 100 * 12 * 2000 // 10000
    assert any("8.33% and 20%" in g for g in r.gaps)


def test_the_hundred_rupee_floor_applies_to_a_tiny_year():
    """§10: 8.33% of the year's salary OR ₹100, whichever is higher."""
    r = _bonus(monthly_salary_paise=500 * 100, months_worked=1)
    assert r.payable_paise == 100 * 100


def test_section_9_disqualification_forfeits_the_whole_bonus():
    """Dismissal for fraud, violence, theft, misappropriation or sabotage —
    and it forfeits all of it, not a part."""
    r = _bonus(disqualified_under_section_9=True)
    assert r.payable_paise == 0
    assert any("§9" in x for x in r.reasons)


# ── IT Act §10(10AA) ─────────────────────────────────────────────────────────

def _leave(**kw):
    kw.setdefault("amount_received_paise", 6_00_000 * 100)
    kw.setdefault("average_monthly_salary_paise", 50_000 * 100)
    kw.setdefault("completed_years_of_service", 20)
    kw.setdefault("leave_days_encashed", 400)
    kw.setdefault("on_retirement", True)
    return L.compute(**kw)


def test_encashment_during_service_is_fully_taxable():
    """The distinction that decides everything. §10(10AA) exempts encashment
    received ON RETIREMENT; encashed in service it is ordinary §17(1) salary,
    and both look identical on a payslip."""
    r = _leave(on_retirement=False, amount_received_paise=1_00_000 * 100)
    assert r.exempt_paise == 0
    assert r.taxable_paise == 1_00_000 * 100
    assert any("ON RETIREMENT" in n for n in r.notes)


def test_a_government_employee_is_wholly_exempt():
    """§10(10AA)(i) — no formula and no limit."""
    r = _leave(is_government_employee=True)
    assert r.exempt_paise == r.received_paise
    assert r.taxable_paise == 0


def test_the_exemption_is_the_least_of_the_four_limbs():
    r = _leave()
    assert r.limb_actual_paise == 6_00_000 * 100
    assert r.limb_statutory_paise == 25_00_000 * 100
    assert r.limb_ten_months_paise == 5_00_000 * 100          # 10 x 50,000
    assert r.limb_leave_credit_paise == 6_66_666_66           # 400/30 x 50,000
    assert r.exempt_paise == 5_00_000 * 100
    assert r.taxable_paise == 1_00_000 * 100


def test_leave_credit_is_capped_at_thirty_days_a_year():
    """Limb 4. An employer whose scheme allows forty-five days a year and pays
    out on that basis is paying more than the section will exempt."""
    generous = _leave(completed_years_of_service=10, leave_days_encashed=450)
    assert generous.days_allowed == 300          # 30 x 10, not 450
    assert any("at most thirty days" in n for n in generous.notes)


def test_the_ceiling_is_twenty_five_lakh_not_three():
    """Notification 31/2023 raised it w.e.f. 01-04-2023, after twenty-five years
    at ₹3,00,000."""
    assert L.LIFETIME_CEILING_PAISE == 25_00_000 * 100


def test_the_lifetime_limit_is_aggregated_across_employers():
    r = _leave(exemption_already_used_paise=24_80_000 * 100)
    assert r.limb_statutory_paise == 20_000 * 100
    assert r.exempt_paise == 20_000 * 100


def test_an_unknown_prior_exemption_is_reported():
    assert any("LIFETIME limit" in g for g in _leave().gaps)


# ── Full and final settlement ────────────────────────────────────────────────

def _settlement(**kw):
    g = G.compute(basic_plus_da_paise=50_000 * 100,
                  joining=date(2015, 4, 1), leaving=date(2025, 9, 30))
    l = L.compute(amount_received_paise=1_50_000 * 100,
                  average_monthly_salary_paise=50_000 * 100,
                  completed_years_of_service=10, leave_days_encashed=60,
                  on_retirement=True)
    b = _bonus(months_worked=6, working_days_in_year=130)
    kw.setdefault("salary_to_last_day_paise", 50_000 * 100)
    kw.setdefault("gratuity", g)
    kw.setdefault("leave", l)
    kw.setdefault("bonus", b)
    return S.build(**kw)


def test_the_settlement_composes_every_entitlement():
    s = _settlement()
    assert [c.label for c in s.components] == [
        "Salary to last working day", "Gratuity", "Leave encashment",
        "Statutory bonus"]
    assert s.gross_paise == 50_000 * 100 + 2_88_461_53 + 1_50_000 * 100 + 3_498_60


def test_exempt_components_do_not_reach_the_taxable_total():
    s = _settlement()
    # Gratuity is fully exempt here; leave is exempt to ₹1,00,000 of ₹1,50,000.
    assert s.taxable_paise == 50_000 * 100 + 50_000 * 100 + 3_498_60


def test_a_recovery_reduces_what_is_paid_but_never_what_is_taxed():
    """Netting notice pay off salary would understate the §17(1) figure that
    reaches Form 16, and with it the TDS. Recovering it does not un-earn the
    salary."""
    plain = _settlement()
    recovered = _settlement(notice_pay_recovered_paise=50_000 * 100)
    assert recovered.taxable_paise == plain.taxable_paise
    assert recovered.net_payable_paise == plain.net_payable_paise - 50_000 * 100
    assert any("DEDUCTION" in g for g in recovered.gaps)


def test_owing_more_than_the_settlement_covers_is_reported_not_floored():
    """Showing a negative net as zero would hide a debt the employer still has
    to collect."""
    s = _settlement(loans_outstanding_paise=99_00_000 * 100)
    assert s.net_payable_paise < 0
    assert any("owes" in p for p in s.problems)


def test_a_component_that_does_not_arise_is_not_a_gap():
    """A resignation at three years has no gratuity, and that is an answer, not
    a missing figure."""
    s = S.build(salary_to_last_day_paise=50_000 * 100)
    assert [c.label for c in s.components] == ["Salary to last working day"]
    assert not s.problems
