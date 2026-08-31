"""
Gratuity — Payment of Gratuity Act 1972 §4, and its tax under IT Act §10(10).

Every figure here is worked from the statute by hand, not read back off the
implementation.
"""
from datetime import date

from domain.payroll import gratuity as G

J = date(2015, 4, 1)


def _c(**kw):
    kw.setdefault("basic_plus_da_paise", 50_000 * 100)
    kw.setdefault("joining", J)
    kw.setdefault("leaving", date(2025, 4, 1))
    return G.compute(**kw)


# ── §4(2): the formula ───────────────────────────────────────────────────────

def test_the_divisor_is_twenty_six_not_thirty():
    """§4(2)'s explanation fixes the daily wage for a monthly-rated employee at
    the monthly rate divided by twenty-six. Using thirty understates gratuity by
    about 15% — the single largest way this calculation goes wrong."""
    r = _c()
    # 50,000 x 15 days x 10 years / 26 = 2,88,461.538...
    assert r.payable_paise == 50_000 * 100 * 15 * 10 // 26
    assert r.payable_paise == 2_88_461_53
    # What the wrong divisor would have produced, for contrast.
    assert 50_000 * 100 * 15 * 10 // 30 == 2_50_000_00


def test_the_formula_is_one_division_not_a_rounded_daily_rate():
    """Flooring the daily wage and then multiplying by 15 x years loses up to
    15 x years paise, always downwards. That is an under-payment of a statutory
    entitlement, and it grows with length of service."""
    r = _c()
    rounded_first = (50_000 * 100 // 26) * 15 * 10
    assert r.payable_paise > rounded_first
    assert r.payable_paise - rounded_first == 103   # ₹1.03 on this example


def test_gratuity_is_on_basic_plus_da_not_gross():
    """§2(s) defines wages as emoluments earned in accordance with the terms of
    employment and EXPRESSLY excludes bonus, commission, HRA and overtime."""
    on_basic_da = _c(basic_plus_da_paise=50_000 * 100).payable_paise
    on_gross = _c(basic_plus_da_paise=90_000 * 100).payable_paise
    assert on_gross > on_basic_da   # the caller must not pass gross


# ── §4(2): "part thereof in excess of six months" ────────────────────────────

def test_six_months_exactly_does_not_round_up():
    assert G.completed_service(J, date(2020, 10, 1)) == (5, 5)


def test_six_months_and_one_day_does_round_up():
    """'In excess of six months' — compared by DATE, not by whole months. A
    whole-month comparison gets this boundary wrong and costs the employee a
    year's gratuity."""
    assert G.completed_service(J, date(2020, 10, 2)) == (5, 6)


def test_the_month_end_clamp_holds():
    """31 August plus six months is 28 February, not an error."""
    assert G.completed_service(date(2015, 8, 31), date(2021, 3, 1)) == (5, 6)


def test_an_incomplete_final_year_under_six_months_is_dropped():
    assert G.completed_service(J, date(2020, 8, 1)) == (5, 5)


# ── §4(1): five years, and the exception that matters ────────────────────────

def test_under_five_years_no_gratuity():
    r = _c(joining=date(2022, 4, 1))
    assert not r.eligible
    assert r.payable_paise == 0
    assert any("§4(1)" in x for x in r.reasons)


def test_death_or_disablement_waives_the_five_years():
    """§4(1)'s proviso: continuous service of five years 'shall not be necessary
    where the termination ... is due to death or disablement'. Refusing gratuity
    to a family because the employee died in year four is the failure mode."""
    r = _c(joining=date(2022, 4, 1), on_death_or_disablement=True)
    assert r.eligible
    assert r.payable_paise > 0


def test_exactly_five_years_qualifies():
    r = _c(joining=date(2020, 4, 1))
    assert r.eligible


# ── §4(3): the ceiling ───────────────────────────────────────────────────────

def test_the_statutory_ceiling_applies():
    """₹20,00,000 since S.O. 1420(E) of 29-03-2018."""
    r = _c(basic_plus_da_paise=5_00_000 * 100, joining=date(1990, 4, 1))
    assert r.payable_paise == 20_00_000 * 100


# ── IT Act §10(10) ───────────────────────────────────────────────────────────

def test_paying_exactly_the_statutory_amount_is_fully_exempt():
    r = _c()
    assert r.exempt_paise == r.payable_paise
    assert r.taxable_paise == 0


def test_paying_more_than_the_act_requires_is_taxable_on_the_excess():
    """The conflation this module exists to prevent: §10(10) exempts the FORMULA
    amount, not whatever the employer chose to pay."""
    r = _c(amount_actually_paid_paise=5_00_000 * 100)
    assert r.payable_paise == 5_00_000 * 100
    assert r.exempt_paise == 2_88_461_53
    assert r.taxable_paise == 5_00_000 * 100 - 2_88_461_53
    assert any("not whatever was paid" in g for g in r.gaps)


def test_the_lifetime_limit_is_aggregated_across_employers():
    """The proviso to §10(10)(iii) makes ₹20,00,000 a lifetime limit. An
    employee who used ₹15,00,000 at a previous employer has ₹5,00,000 left."""
    r = _c(basic_plus_da_paise=5_00_000 * 100, joining=date(1990, 4, 1),
           exemption_already_used_paise=15_00_000 * 100)
    assert r.exempt_paise == 5_00_000 * 100
    assert r.taxable_paise == 15_00_000 * 100


def test_an_unknown_prior_exemption_is_reported_not_assumed_away():
    """Assuming the full limit is available under-taxes, which is the dangerous
    direction. It is stated as a gap rather than silently taken."""
    r = _c()
    assert any("LIFETIME limit" in g for g in r.gaps)


def test_an_uncovered_employee_uses_the_other_formula():
    """§10(10)(iii): half a month's AVERAGE salary of the last ten months for
    each COMPLETED year — a different divisor, and part years are dropped rather
    than rounded up."""
    r = _c(leaving=date(2025, 11, 1), covered_by_the_act=False,
           average_last_ten_months_paise=48_000 * 100)
    assert r.service_years_counted == 11    # §4 rounds the part year up
    assert r.completed_years == 10          # §10(10)(iii) does not
    assert r.exempt_paise == 48_000 * 100 * 15 // 30 * 10
    assert r.exempt_paise == 2_40_000 * 100


def test_an_uncovered_employee_without_the_average_says_so():
    r = _c(covered_by_the_act=False)
    assert any("AVERAGE" in g for g in r.gaps)


# ── Refusals rather than plausible zeroes ────────────────────────────────────

def test_a_missing_joining_date_is_a_reason_not_a_zero():
    """The bug this replaces displayed zero gratuity for everyone because it
    read a column that does not exist. A zero and 'we do not know when they
    joined' must never look the same."""
    r = _c(joining=None)
    assert r.payable_paise == 0
    assert any("joining date" in x for x in r.reasons)


def test_no_wages_is_a_reason_not_a_zero():
    r = _c(basic_plus_da_paise=0)
    assert not r.eligible
    assert any("§2(s)" in x for x in r.reasons)
