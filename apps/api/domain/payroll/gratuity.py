"""
Gratuity — Payment of Gratuity Act 1972, and its tax under IT Act §10(10).

TWO DIFFERENT QUESTIONS, AND THEY HAVE DIFFERENT ANSWERS

    What is PAYABLE — Payment of Gratuity Act 1972 §4. A statutory entitlement:
    fifteen days' wages for every completed year of service, on the wages last
    drawn, subject to §4(3)'s ceiling.

    What is TAXABLE — IT Act §10(10). An exemption computed separately, with its
    own limit and its own lifetime aggregation across employers.

They are routinely conflated, and the conflation is invisible because both
numbers look like "the gratuity". An employer who pays more than the Act
requires — many do — owes tax on the excess above the §10(10) exemption, and a
payroll system that exempts whatever it paid understates the employee's income.

WHAT §4 ACTUALLY SAYS

  §4(1)  Gratuity is payable on termination after FIVE YEARS of continuous
         service — on superannuation, retirement or resignation, or on death or
         disablement. The five-year condition "shall not be necessary where the
         termination is due to death or disablement", which is the exception
         this module models rather than a rounding case: refusing gratuity to a
         family because the employee died in year four is the failure mode.

  §4(2)  "fifteen days' wages based on the rate of wages last drawn ... for
         every completed year of service or part thereof in excess of six
         months". The daily rate is the monthly wage divided by TWENTY-SIX, not
         thirty — the Act's explanation says so for monthly-rated employees, and
         26 rather than 30 is worth about 15% of the answer.

  §4(3)  The ceiling. ₹20,00,000 since Notification S.O. 1420(E) of 29-03-2018.

  §2(s)  "Wages" means all emoluments earned in accordance with the terms of
         employment — basic and dearness allowance — and expressly EXCLUDES
         bonus, commission, house rent allowance, overtime and any other
         allowance. So gratuity is on Basic + DA, never on gross.

WHAT §10(10) SAYS

  §10(10)(ii)  Employees COVERED by the Act: exempt to the least of the actual
               gratuity, the §4 formula amount, and ₹20,00,000.
  §10(10)(iii) Employees NOT covered: half a month's average salary of the last
               ten months for each completed year (part years ignored), the
               actual gratuity, or ₹20,00,000 — least of the three. Note both
               the different divisor and that part years are DROPPED, not
               rounded up.

  The ₹20,00,000 is a LIFETIME limit aggregated across employers (the proviso to
  §10(10)(iii)), so an employee who has already used part of it at a previous
  employer has less left. This module takes that as an input and says so when it
  is not supplied, rather than assuming the full limit is available — assuming
  it is the dangerous direction, since it under-taxes.

WHY COVERAGE IS AN INPUT

The Act applies to establishments with ten or more employees (§1(3)), and once
it has applied it continues to apply even if the number later falls (§1(3A)).
Neither fact is derivable from a payroll run: today's headcount is not the
headcount on the qualifying date, and §1(3A) means a small establishment may
still be covered because it was once bigger. So `covered_by_the_act` is a field.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

# Payment of Gratuity Act §4(3), as raised by S.O. 1420(E) of 29-03-2018.
GRATUITY_CEILING_PAISE: int = 20_00_000 * 100

# §4(1) — five years of continuous service, except on death or disablement.
QUALIFYING_YEARS: int = 5

# §4(2)'s explanation: for a monthly-rated employee the daily wage is the
# monthly rate divided by twenty-six. Not thirty — the difference is ~15%.
DAYS_IN_MONTH_FOR_GRATUITY: int = 26
DAYS_PER_YEAR_OF_SERVICE: int = 15

# §10(10)(iii) — the uncovered formula is half a month per completed year.
UNCOVERED_DAYS_PER_YEAR: int = 15
UNCOVERED_DIVISOR: int = 30


@dataclass
class GratuityResult:
    payable_paise: int = 0
    exempt_paise: int = 0
    taxable_paise: int = 0

    completed_years: int = 0
    service_years_counted: int = 0     # after §4(2)'s "part thereof" rounding
    daily_wage_paise: int = 0

    eligible: bool = False
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


def _add_months(d: date, months: int) -> date:
    """d shifted by whole months, clamped to the end of a shorter month.

    31 August plus six months is 28 (or 29) February, not an error. Written out
    rather than pulled from dateutil, which is not a dependency here.
    """
    total = d.month - 1 + months
    year = d.year + total // 12
    month = total % 12 + 1
    day = d.day
    while True:
        try:
            return date(year, month, day)
        except ValueError:
            day -= 1        # 31st of a 30-day month, 29 Feb in a common year


def completed_service(joining: date, leaving: date) -> tuple[int, int]:
    """(whole years served, years counted for §4(2)).

    §4(2) counts "every completed year of service or part thereof IN EXCESS OF
    six months". Compared by date rather than by whole months, because the
    difference is a real one: six months and one day IS in excess of six months
    and rounds the count up, while six months exactly is not and does not. A
    whole-month comparison gets the boundary day wrong and costs the employee a
    year's gratuity.
    """
    if leaving < joining:
        return 0, 0
    years = leaving.year - joining.year
    if (leaving.month, leaving.day) < (joining.month, joining.day):
        years -= 1
    years = max(0, years)

    last_anniversary = _add_months(joining, years * 12)
    counted = years + (1 if leaving > _add_months(last_anniversary, 6) else 0)
    return years, counted


def compute(
    *,
    basic_plus_da_paise: int,
    joining: date | None,
    leaving: date | None,
    covered_by_the_act: bool = True,
    on_death_or_disablement: bool = False,
    amount_actually_paid_paise: int | None = None,
    exemption_already_used_paise: int | None = None,
    average_last_ten_months_paise: int | None = None,
) -> GratuityResult:
    """What is payable under §4, and how much of it §10(10) exempts.

    `amount_actually_paid_paise` of None means the employer is paying exactly
    the statutory amount, which is the common case. Where an employer pays more
    — an ex gratia top-up, a better contractual scheme — passing the real figure
    is what makes the taxable half correct: §10(10) exempts the FORMULA amount,
    not whatever was paid.
    """
    out = GratuityResult()

    if not joining or not leaving:
        out.reasons.append(
            "Gratuity needs a joining date and a leaving date. Without both, "
            "length of service cannot be established and §4(2) has nothing to "
            "count."
        )
        return out

    years, counted = completed_service(joining, leaving)
    out.completed_years = years
    out.service_years_counted = counted

    if basic_plus_da_paise <= 0:
        out.reasons.append(
            "Gratuity is computed on wages as §2(s) defines them — basic and "
            "dearness allowance, expressly excluding bonus, commission, HRA and "
            "overtime. No basic or DA is recorded for this employee."
        )
        return out

    # §4(1): five years, unless death or disablement.
    if years < QUALIFYING_YEARS and not on_death_or_disablement:
        out.reasons.append(
            f"{years} completed year{'' if years == 1 else 's'} of service. §4(1) "
            f"requires five, and the exception for death or disablement does not "
            f"apply here."
        )
        return out

    out.eligible = True

    # §4(2), as ONE division rather than a rounded daily rate multiplied out.
    # Flooring the daily wage first and then multiplying by 15 × years loses up
    # to 15 × years paise, always downwards — an under-payment of a statutory
    # entitlement that grows with length of service. The Act speaks of "fifteen
    # days' wages based on the rate of wages last drawn", which is one
    # computation, not fifteen rounded ones.
    out.daily_wage_paise = basic_plus_da_paise // DAYS_IN_MONTH_FOR_GRATUITY
    formula = (basic_plus_da_paise * DAYS_PER_YEAR_OF_SERVICE * counted
               // DAYS_IN_MONTH_FOR_GRATUITY)
    statutory = min(formula, GRATUITY_CEILING_PAISE)

    paid = statutory if amount_actually_paid_paise is None else max(0, amount_actually_paid_paise)
    out.payable_paise = paid

    # ── §10(10) ──────────────────────────────────────────────────────────────
    limit = GRATUITY_CEILING_PAISE
    if exemption_already_used_paise is None:
        out.gaps.append(
            "The ₹20,00,000 under §10(10) is a LIFETIME limit aggregated across "
            "employers. Nothing is recorded about gratuity exempted at a previous "
            "employer, so the full limit is assumed available. Where the employee "
            "has had gratuity before, the exemption here is smaller and the "
            "taxable amount larger."
        )
    else:
        limit = max(0, GRATUITY_CEILING_PAISE - max(0, exemption_already_used_paise))

    if covered_by_the_act:
        # §10(10)(ii): least of actual, the §4 formula, and the limit.
        out.exempt_paise = min(paid, formula, limit)
    else:
        # §10(10)(iii): half a month's AVERAGE salary of the last ten months,
        # per COMPLETED year — part years are dropped here, not rounded up.
        if average_last_ten_months_paise is None:
            out.gaps.append(
                "This employee is not covered by the Payment of Gratuity Act, so "
                "§10(10)(iii) applies: the exemption is half a month's AVERAGE "
                "salary of the last ten months, per completed year. That average "
                "is not supplied, so the last drawn wage is used instead. Where "
                "pay changed in the final ten months the two differ, and the "
                "average is the one the section asks for."
            )
            average = basic_plus_da_paise
        else:
            average = max(0, average_last_ten_months_paise)
        uncovered_formula = (average * UNCOVERED_DAYS_PER_YEAR // UNCOVERED_DIVISOR) * years
        out.exempt_paise = min(paid, uncovered_formula, limit)

    out.taxable_paise = max(0, paid - out.exempt_paise)

    if amount_actually_paid_paise is not None and paid > statutory:
        out.gaps.append(
            f"₹{paid / 100:,.2f} is being paid against a statutory entitlement of "
            f"₹{statutory / 100:,.2f}. §10(10) exempts the FORMULA amount, not "
            f"whatever was paid, so the excess is taxable salary and belongs in "
            f"the year's §17(1) figure."
        )

    return out
