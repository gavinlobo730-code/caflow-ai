"""
Perquisites — IT Act §17(2), valued under Rule 3 of the Income-tax Rules 1962.
"""
from domain.payroll import perquisites as P

SALARY = 10_00_000 * 100      # Rule 3's "salary", not gross and not §17(1)


# ── Rule 3(1): accommodation ─────────────────────────────────────────────────

def test_the_2023_rates_apply_from_2024_25():
    """Notification 65/2023 of 18-08-2023 substituted 15/10/7.5 per cent on
    25-lakh and 10-lakh thresholds with 10/7.5/5 on 40-lakh and 15-lakh ones,
    taken from the 2011 census. A payroll still on the old table over-values the
    perquisite by half."""
    for pop, expected_bps in ((50, 1000), (20, 750), (5, 500)):
        p, _ = P.value_accommodation(fy="2025-26", salary_for_rule_3_paise=SALARY,
                                     population_lakh=pop)
        assert p.value_paise == SALARY * expected_bps // 10000, pop


def test_a_year_before_the_amendment_uses_the_old_table():
    """The rates are FY-versioned rather than constants, so a valuation for a
    closed year is done at the rates that applied to it."""
    p, _ = P.value_accommodation(fy="2022-23", salary_for_rule_3_paise=SALARY,
                                 population_lakh=50)
    assert p.value_paise == SALARY * 1500 // 10000
    assert "pre-2023 rates" in p.note


def test_the_transition_year_is_flagged_rather_than_guessed():
    """The notification took effect on 01-09-2023, part way through FY 2023-24.
    A full-year valuation needs apportioning, and silently choosing one table
    would be a decision nobody made."""
    _, gaps = P.value_accommodation(fy="2023-24", salary_for_rule_3_paise=SALARY,
                                    population_lakh=50)
    assert any("01-09-2023" in g and "apportioning" in g for g in gaps)


def test_leased_accommodation_is_the_lower_of_rent_and_ten_percent():
    cheap, _ = P.value_accommodation(
        fy="2025-26", salary_for_rule_3_paise=SALARY, population_lakh=50,
        employer_owns=False, actual_lease_rent_paise=60_000 * 100)
    assert cheap.value_paise == 60_000 * 100          # the rent is lower

    dear, _ = P.value_accommodation(
        fy="2025-26", salary_for_rule_3_paise=SALARY, population_lakh=50,
        employer_owns=False, actual_lease_rent_paise=6_00_000 * 100)
    assert dear.value_paise == SALARY * 1000 // 10000  # 10% of salary is lower


def test_rent_paid_by_the_employee_reduces_the_value():
    p, _ = P.value_accommodation(
        fy="2025-26", salary_for_rule_3_paise=SALARY, population_lakh=50,
        rent_recovered_from_employee_paise=40_000 * 100)
    assert p.value_paise == SALARY * 1000 // 10000 - 40_000 * 100


def test_part_year_accommodation_is_apportioned():
    p, _ = P.value_accommodation(fy="2025-26", salary_for_rule_3_paise=SALARY,
                                 population_lakh=50, months=6)
    assert p.value_paise == (SALARY * 6 // 12) * 1000 // 10000


# ── Rule 3(2): motor car ─────────────────────────────────────────────────────

def test_the_car_table_is_a_monthly_figure_not_a_percentage():
    small, _ = P.value_motor_car(engine_litres=1.4)
    assert small.value_paise == 1_800 * 100 * 12

    large, _ = P.value_motor_car(engine_litres=2.0)
    assert large.value_paise == 2_400 * 100 * 12


def test_the_threshold_is_1_6_litres():
    assert P.value_motor_car(engine_litres=1.6)[0].value_paise == 1_800 * 100 * 12
    assert P.value_motor_car(engine_litres=1.61)[0].value_paise == 2_400 * 100 * 12


def test_who_bears_the_running_costs_changes_the_figure():
    employer, _ = P.value_motor_car(engine_litres=1.4, employer_bears_running_costs=True)
    employee, _ = P.value_motor_car(engine_litres=1.4, employer_bears_running_costs=False)
    assert employer.value_paise == 1_800 * 100 * 12
    assert employee.value_paise == 600 * 100 * 12


def test_a_driver_adds_nine_hundred_a_month():
    with_driver, _ = P.value_motor_car(engine_litres=2.0, with_driver=True)
    assert with_driver.value_paise == (2_400 + 900) * 100 * 12


def test_wholly_official_use_is_nil_but_conditional():
    p, _ = P.value_motor_car(wholly_official=True)
    assert p.value_paise == 0
    assert "records" in p.note


def test_wholly_personal_use_is_refused_not_guessed():
    """Sl. No. 1(b) needs the actual running expenditure, 10% a year of the
    car's cost and the driver's salary — none of which payroll holds."""
    item, gaps = P.value_motor_car(wholly_personal=True)
    assert item is None
    assert any("actual running" in g for g in gaps)


# ── Rule 3(7)(i): concessional loan ──────────────────────────────────────────

def test_the_loan_is_valued_at_the_sbi_rate_less_what_was_charged():
    p, _ = P.value_concessional_loan(
        maximum_monthly_outstanding_paise=5_00_000 * 100,
        sbi_rate_bps_on_first_day=890,
        interest_actually_charged_paise=10_000 * 100)
    assert p.value_paise == 5_00_000 * 100 * 890 // 10000 - 10_000 * 100


def test_a_missing_sbi_rate_refuses_the_valuation():
    """The rate is published annually and is not derivable. Guessing it would
    put an invented figure in someone's Form 16."""
    item, gaps = P.value_concessional_loan(
        maximum_monthly_outstanding_paise=5_00_000 * 100,
        sbi_rate_bps_on_first_day=None)
    assert item is None
    assert any("STATE BANK OF INDIA" in g for g in gaps)


def test_twenty_thousand_or_less_is_outside_the_charge():
    p, _ = P.value_concessional_loan(
        maximum_monthly_outstanding_paise=20_000 * 100,
        sbi_rate_bps_on_first_day=890)
    assert p.value_paise == 0


def test_a_loan_for_a_specified_disease_is_outside_the_charge():
    p, _ = P.value_concessional_loan(
        maximum_monthly_outstanding_paise=5_00_000 * 100,
        sbi_rate_bps_on_first_day=890, for_specified_disease=True)
    assert p.value_paise == 0
    assert "rule 3A" in p.note


# ── Rule 3(7)(iii) and (iv): the small ones ──────────────────────────────────

def test_meals_are_exempt_to_fifty_rupees_each():
    p = P.value_meals(meals_provided=200, cost_per_meal_paise=80 * 100)
    assert p.value_paise == 30 * 100 * 200

    assert P.value_meals(meals_provided=200, cost_per_meal_paise=45 * 100).value_paise == 0


def test_gifts_lose_only_the_excess_over_five_thousand():
    """The ₹5,000 is exempt IN AGGREGATE and is not lost by exceeding it —
    ₹6,000 of gifts is taxable as to ₹1,000, not as to ₹6,000."""
    assert P.value_gifts(total_gifts_paise=6_000 * 100).value_paise == 1_000 * 100
    assert P.value_gifts(total_gifts_paise=5_000 * 100).value_paise == 0
