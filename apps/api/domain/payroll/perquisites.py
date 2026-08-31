"""
Perquisites — IT Act §17(2), valued under Rule 3 of the Income-tax Rules 1962.

WHY THIS IS THE LAST ANNEXURE II GAP

24Q Annexure II — the input TRACES generates Form 16 Part B from — has a column
for §17(2) perquisites. Payroll could fill in every other column from the
payslips and this one from nothing, so it reported it as a gap. Perquisites are
the employer's to value: the employer provides the car, the flat, the
interest-free loan, and Rule 3 tells the employer what each is worth. No
employee declaration can supply it.

WHAT IS MODELLED, AND WHAT EACH RULE ACTUALLY SAYS

  Rule 3(1) — ACCOMMODATION. Substantially rewritten by Notification 65/2023 of
    18-08-2023, with effect from 01-09-2023. For accommodation OWNED by a
    non-government employer the value is a percentage of salary, by the city's
    population at the 2011 census:

        over 40 lakh                  10%
        over 15 lakh, up to 40 lakh    7.5%
        up to 15 lakh                  5%

    Before that amendment the rates were 15% / 10% / 7.5% on 25-lakh and
    10-lakh thresholds taken from the 2001 census. A payroll still using those
    over-values the perquisite by half, so the rates are FY-versioned here
    rather than written as constants.

    Where the employer TAKES THE ACCOMMODATION ON LEASE the value is the lower
    of the actual rent and 10% of salary. Either way it is reduced by rent the
    employee actually pays.

  Rule 3(2) — MOTOR CAR. A table, not a formula, and the figures are monthly:

        employer's car, employer bears running costs, part-personal use
            engine up to 1.6 litre      1,800 a month
            engine over 1.6 litre       2,400 a month
        employer's car, EMPLOYEE bears running costs, part-personal use
            engine up to 1.6 litre        600 a month
            engine over 1.6 litre         900 a month
        a driver, in either case         +900 a month

    Wholly official use is nil, subject to the records the rule requires.
    Wholly personal use is the actual expenditure plus 10% a year of the car's
    cost, which needs figures payroll does not hold — so that case is reported
    rather than guessed.

  Rule 3(7)(i) — INTEREST-FREE OR CONCESSIONAL LOAN. Interest at the State Bank
    of India's rate for the same kind of loan AS ON THE FIRST DAY of the
    previous year, less interest actually charged, on the maximum outstanding
    monthly balance. Nothing is chargeable where the aggregate of such loans
    does not exceed ₹20,000, or for medical treatment of a specified disease.

    The SBI rate is published annually and is not derivable — it is an input,
    and where it is absent this module refuses the valuation rather than
    inventing a rate.

  Rule 3(7)(iii) — FREE OR CONCESSIONAL FOOD: exempt to ₹50 per meal.
  Rule 3(7)(iv) — GIFTS: exempt to ₹5,000 in aggregate for the year. Note it is
    the aggregate that is exempt, so a ₹6,000 gift is taxable as to ₹1,000, not
    as to ₹6,000.

WHAT "SALARY" MEANS HERE

Not gross, and not §17(1). The Explanation to Rule 3 defines it for this rule as
basic, dearness allowance where the terms of employment so provide, bonus,
commission, fees and all taxable allowances — but EXCLUDING dearness allowance
that does not enter retirement benefits, the employer's provident fund
contribution, allowances exempt under §10, and the value of the perquisites
themselves. Passing gross inflates every percentage-based valuation, so the
caller supplies this figure explicitly and it is named for what it is.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from dataclasses import dataclass, field

# ── Rule 3(1), as substituted by Notification 65/2023 w.e.f. 01-09-2023 ──────
# (population threshold in lakh, percentage of salary in basis points)
ACCOMMODATION_RATES_FROM_2023_24: tuple[tuple[int, int], ...] = (
    (40, 1000),    # over 40 lakh -> 10%
    (15, 750),     # over 15 lakh, up to 40 -> 7.5%
    (0, 500),      # up to 15 lakh -> 5%
)
# The pre-amendment table, kept so a year before FY 2023-24 is valued at the
# rates that applied to it rather than at today's.
ACCOMMODATION_RATES_BEFORE_2023_24: tuple[tuple[int, int], ...] = (
    (25, 1500),    # over 25 lakh -> 15%
    (10, 1000),    # over 10 lakh, up to 25 -> 10%
    (0, 750),      # up to 10 lakh -> 7.5%
)
# The first financial year in which the substituted rates apply throughout.
# (The notification took effect 01-09-2023, part way through FY 2023-24; a
# valuation spanning that date needs apportioning, which is flagged rather than
# silently done one way or the other.)
ACCOMMODATION_NEW_RATES_FROM_FY: str = "2024-25"
ACCOMMODATION_TRANSITION_FY: str = "2023-24"

# Rule 3(1) — employer-leased accommodation: lower of actual rent and this.
LEASED_ACCOMMODATION_CAP_BPS: int = 1000     # 10% of salary

# ── Rule 3(2) — the motor car table, per MONTH ──────────────────────────────
CAR_SMALL_EMPLOYER_BEARS_PAISE: int = 1_800 * 100
CAR_LARGE_EMPLOYER_BEARS_PAISE: int = 2_400 * 100
CAR_SMALL_EMPLOYEE_BEARS_PAISE: int = 600 * 100
CAR_LARGE_EMPLOYEE_BEARS_PAISE: int = 900 * 100
CAR_DRIVER_PAISE: int = 900 * 100
CAR_ENGINE_LITRES_THRESHOLD: float = 1.6

# ── Rule 3(7) — the small exemptions ────────────────────────────────────────
LOAN_DE_MINIMIS_PAISE: int = 20_000 * 100     # 3(7)(i)
MEAL_EXEMPT_PER_MEAL_PAISE: int = 50 * 100    # 3(7)(iii)
GIFT_EXEMPT_PER_YEAR_PAISE: int = 5_000 * 100  # 3(7)(iv)


@dataclass
class Perquisite:
    label: str
    value_paise: int = 0
    rule: str = ""
    note: str = ""


@dataclass
class PerquisiteResult:
    items: list[Perquisite] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def total_paise(self) -> int:
        return sum(i.value_paise for i in self.items)


def accommodation_rate_bps(fy: str, population_lakh: int) -> tuple[int, str]:
    """(rate in basis points, the note explaining which table was used)."""
    table = (ACCOMMODATION_RATES_FROM_2023_24
             if fy >= ACCOMMODATION_NEW_RATES_FROM_FY
             else ACCOMMODATION_RATES_BEFORE_2023_24)
    which = ("Notification 65/2023 rates" if table is ACCOMMODATION_RATES_FROM_2023_24
             else "the pre-2023 rates")
    for threshold, bps in table:
        if population_lakh > threshold:
            return bps, which
    return table[-1][1], which


def value_accommodation(
    *,
    fy: str,
    salary_for_rule_3_paise: int,
    population_lakh: int,
    months: int = 12,
    employer_owns: bool = True,
    actual_lease_rent_paise: int = 0,
    rent_recovered_from_employee_paise: int = 0,
) -> tuple[Perquisite, list[str]]:
    """Rule 3(1) — rent-free or concessional accommodation, non-government."""
    gaps: list[str] = []
    months = max(0, min(12, int(months)))
    salary = max(0, salary_for_rule_3_paise) * months // 12

    if fy == ACCOMMODATION_TRANSITION_FY:
        gaps.append(
            "Notification 65/2023 substituted the accommodation rates with effect "
            "from 01-09-2023, part way through FY 2023-24. A full-year valuation "
            "for that year needs apportioning between the old and new rates; the "
            "pre-amendment table was used here for the whole year. Check the "
            "split before relying on it."
        )

    if employer_owns:
        bps, which = accommodation_rate_bps(fy, population_lakh)
        gross = salary * bps // 10000
        note = (f"{bps / 100:g}% of salary — {which}, population "
                f"{population_lakh} lakh (2011 census).")
    else:
        # Lower of the actual rent and 10% of salary.
        cap = salary * LEASED_ACCOMMODATION_CAP_BPS // 10000
        rent = max(0, actual_lease_rent_paise)
        gross = min(rent, cap)
        note = ("Taken on lease: the lower of the rent paid "
                f"(₹{rent / 100:,.2f}) and 10% of salary (₹{cap / 100:,.2f}).")

    value = max(0, gross - max(0, rent_recovered_from_employee_paise))
    return Perquisite(label="Accommodation", value_paise=value,
                      rule="Rule 3(1)", note=note), gaps


def value_motor_car(
    *,
    months: int = 12,
    engine_litres: float = 1.4,
    employer_bears_running_costs: bool = True,
    with_driver: bool = False,
    wholly_official: bool = False,
    wholly_personal: bool = False,
    amount_recovered_paise: int = 0,
) -> tuple[Perquisite | None, list[str]]:
    """Rule 3(2) — a car provided by the employer."""
    gaps: list[str] = []
    months = max(0, min(12, int(months)))

    if wholly_official:
        return Perquisite(
            label="Motor car", value_paise=0, rule="Rule 3(2)",
            note="Wholly for official use — nil, provided the employer keeps the "
                 "records the rule requires: details of journeys, and a "
                 "certificate that the expenditure was wholly official."), gaps

    if wholly_personal:
        gaps.append(
            "A car used wholly for private purposes is valued at the actual "
            "running and maintenance expenditure, plus 10% a year of the car's "
            "cost (or the hire charges), plus the driver's salary, less anything "
            "recovered. None of those figures is in payroll, so this cannot be "
            "valued here — Rule 3(2) Sl. No. 1(b)."
        )
        return None, gaps

    large = engine_litres > CAR_ENGINE_LITRES_THRESHOLD
    if employer_bears_running_costs:
        monthly = CAR_LARGE_EMPLOYER_BEARS_PAISE if large else CAR_SMALL_EMPLOYER_BEARS_PAISE
        who = "employer bears the running costs"
    else:
        monthly = CAR_LARGE_EMPLOYEE_BEARS_PAISE if large else CAR_SMALL_EMPLOYEE_BEARS_PAISE
        who = "employee bears the running costs"
    if with_driver:
        monthly += CAR_DRIVER_PAISE

    value = max(0, monthly * months - max(0, amount_recovered_paise))
    return Perquisite(
        label="Motor car", value_paise=value, rule="Rule 3(2)",
        note=(f"Part official, part personal; {who}; engine "
              f"{'over' if large else 'up to'} 1.6 litre"
              f"{'; with driver' if with_driver else ''}. "
              f"₹{monthly / 100:,.0f} a month for {months} months.")), gaps


def value_concessional_loan(
    *,
    maximum_monthly_outstanding_paise: int,
    sbi_rate_bps_on_first_day: int | None,
    interest_actually_charged_paise: int = 0,
    months: int = 12,
    for_specified_disease: bool = False,
) -> tuple[Perquisite | None, list[str]]:
    """Rule 3(7)(i) — an interest-free or concessional loan."""
    gaps: list[str] = []
    outstanding = max(0, maximum_monthly_outstanding_paise)

    if for_specified_disease:
        return Perquisite(
            label="Concessional loan", value_paise=0, rule="Rule 3(7)(i)",
            note="Nil — a loan for the medical treatment of a disease specified "
                 "in rule 3A is outside the charge."), gaps

    if outstanding <= LOAN_DE_MINIMIS_PAISE:
        return Perquisite(
            label="Concessional loan", value_paise=0, rule="Rule 3(7)(i)",
            note=f"Nil — the aggregate does not exceed ₹20,000."), gaps

    if sbi_rate_bps_on_first_day is None:
        gaps.append(
            "Rule 3(7)(i) values the benefit at the STATE BANK OF INDIA's rate "
            "for the same kind of loan as on the FIRST DAY of the previous year, "
            "less any interest actually charged. That rate is published annually "
            "and is not derivable here, so the loan is not valued. Supplying a "
            "guess would put an invented figure in someone's Form 16."
        )
        return None, gaps

    months = max(0, min(12, int(months)))
    notional = outstanding * max(0, sbi_rate_bps_on_first_day) * months // (10000 * 12)
    value = max(0, notional - max(0, interest_actually_charged_paise))
    return Perquisite(
        label="Concessional loan", value_paise=value, rule="Rule 3(7)(i)",
        note=(f"SBI rate {sbi_rate_bps_on_first_day / 100:g}% on a maximum "
              f"outstanding of ₹{outstanding / 100:,.2f} for {months} months, "
              f"less ₹{interest_actually_charged_paise / 100:,.2f} charged.")), gaps


def value_meals(*, meals_provided: int, cost_per_meal_paise: int) -> Perquisite:
    """Rule 3(7)(iii) — free or concessional food, exempt to ₹50 a meal."""
    excess = max(0, cost_per_meal_paise - MEAL_EXEMPT_PER_MEAL_PAISE)
    return Perquisite(
        label="Free or concessional meals", value_paise=excess * max(0, meals_provided),
        rule="Rule 3(7)(iii)",
        note=f"₹{cost_per_meal_paise / 100:,.2f} a meal, of which ₹50 is exempt.")


def value_gifts(*, total_gifts_paise: int) -> Perquisite:
    """Rule 3(7)(iv) — gifts, with ₹5,000 exempt IN AGGREGATE for the year.

    The aggregate is exempt, not each gift, and the exemption is not lost by
    exceeding it: ₹6,000 of gifts is taxable as to ₹1,000.
    """
    total = max(0, total_gifts_paise)
    return Perquisite(
        label="Gifts", value_paise=max(0, total - GIFT_EXEMPT_PER_YEAR_PAISE),
        rule="Rule 3(7)(iv)",
        note="₹5,000 of the year's aggregate is exempt; only the excess is "
             "chargeable.")
