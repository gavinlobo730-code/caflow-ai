"""
Gratuity — section 53 of the Code on Social Security, 2020, and its tax under IT Act §10(10).

SECTION 53 REPLACED THE PAYMENT OF GRATUITY ACT, 1972 FROM 21-11-2025, AND THE CEILING AND THE BASE BELOW ARE THE ACT'S (POST-A-526)

    The Code repealed the Payment of Gratuity Act, 1972 from 21-11-2025 (section 164(1)) and the Social Security (Central) Rules, 2026
    (G.S.R. 344(E), rules 31 to 34) took the place of the Act's Central Rules. The formula this module computes (fifteen days' wages for
    every completed year of service or part of a year over six months, a daily wage of the monthly wage over twenty-six, five years'
    continuous service) is the same in section 53. What section 53 does NOT state, and this module therefore carries over from the
    repealed Act and says so on every settlement that includes a gratuity (`CARRIED_OVER_FROM_THE_REPEALED_ACT`):

      * the CEILING. Section 53(3) leaves it to "such amount as may be notified". Rs 20,00,000 is S.O. 1420(E) of 29-03-2018 under
        the Act and continues only if section 164(2)(a) keeps it; no notification under section 53 has been read. The number of days
        in section 53(2) may likewise be notified.
      * the BASE. It is basic plus dearness allowance, the Act's "wages"; the Code speaks of "wages" defined once, in section 2(88),
        whose one-half rule may enlarge the base for a termination after 21-11-2025. That is a legal reading for a CA (owner list S50),
        and nothing here applies it.

    A FIXED-TERM EMPLOYEE'S FIVE YEARS ARE WAIVED ON THE EXPIRY OF THE TERM, AND THE ONE-YEAR LINE IS THE RULES' (POST-A-526, migration 770)

        Section 53(1)(d) makes gratuity payable "on termination of his contract period under fixed term employment", and its second
        proviso says "the completion of continuous service of five years shall not be necessary where the termination of the employment
        of any employee is due to death or disablement or expiration of fixed term employment". Rule 33(1)(a) of the Social Security
        (Central) Rules, 2026 adds, in its own second proviso: "an employee on fixed term employment shall be eligible for gratuity, if
        he renders service under the contract for a period of at least one year and for subsequent period in excess of six months and
        more, but less than one year, shall be rounded off to one additional year". The third proviso to section 53(2) makes the
        gratuity pro rata, which is the same formula over the service rendered. So an employee RECORDED AS ON FIXED-TERM EMPLOYMENT
        whose employment ENDS BY THE EXPIRY OF THE TERM needs ONE completed year, not five (`fixed_term=True, fixed_term_expired=True`).

        What the text read does NOT settle is a fixed-term employee who resigns or is dismissed BEFORE the term ends: section 53(1)(b)
        makes a resignation payable only after five years, the Rule's sentence names one year under the contract without naming expiry,
        and nothing read says how the two fit. The module therefore does for that case what it did before, five years, and says why in
        the reason it returns (owner list S50). Both inputs are facts and neither is inferred: `fixed_term` is recorded on the employee,
        and `fixed_term_expired` is stated by whoever records the settlement or read from the contract's recorded end date having been
        reached (`fixed_term_has_expired`). A short service never decides either. Service is counted from the joining date, so it is
        taken as service under the one contract.

    Everything below that quotes "§4" or "§2(s)" quotes the repealed Act, which is where the figures came from; "§10(10)" is the Income-tax
    Act, 1961, whose replacement from 01-04-2026 is a separate reading (owner list D8 and D9).

TWO DIFFERENT QUESTIONS, AND THEY HAVE DIFFERENT ANSWERS

    What is PAYABLE — section 53 of the Code (the repealed Act's §4). A statutory entitlement:
    fifteen days' wages for every completed year of service, on the wages last
    drawn, subject to the ceiling (the repealed Act's §4(3), section 53(3) now).

    What is TAXABLE — IT Act §10(10). An exemption computed separately, with its
    own limit and its own lifetime aggregation across employers.

They are routinely conflated, and the conflation is invisible because both
numbers look like "the gratuity". An employer who pays more than the Act
requires — many do — owes tax on the excess above the §10(10) exemption, and a
payroll system that exempts whatever it paid understates the employee's income.

WHAT THE REPEALED ACT'S §4 SAID, WHICH SECTION 53 REPEATS (the ceiling and the wages excepted, above)

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
from domain.money_sentence import rupee_text

# The repealed Payment of Gratuity Act's §4(3), as raised by S.O. 1420(E) of 29-03-2018. Section 53(3) of the Code leaves the amount to a
# notification (POST-A-526); none has been read, so this figure is carried over and every settlement says so.
GRATUITY_CEILING_PAISE: int = 20_00_000 * 100

#: Said on every settlement that includes a gratuity, because the two figures it names move money and nothing in the Code's text read
#: settles either (owner list S50). It states what is carried over; it does not decide it.
CARRIED_OVER_FROM_THE_REPEALED_ACT = (
    "Gratuity is computed under section 53 of the Code on Social Security, 2020, which replaced the Payment of Gratuity Act, 1972 on "
    "21-11-2025. Two figures are carried over from the repealed Act because the Code leaves them to a notification or a definition "
    "that has not been applied here: the ceiling of Rs 20,00,000 (section 53(3) says \"such amount as may be notified\", and no "
    "notification under it has been read) and the base of basic pay plus dearness allowance (the Code defines wages in section 2(88), "
    "which may give a larger base for a termination after 21-11-2025). A CA should confirm both before the amount is paid."
)

# §4(1) — five years of continuous service, except on death or disablement.
QUALIFYING_YEARS: int = 5

# A fixed-term employee: one year of service under the contract (the second proviso to section 53(1); rule 33(1)(a) of the Social Security
# (Central) Rules, 2026). The part of a year over six months counts as a year by the same rounding as for anybody else.
FIXED_TERM_QUALIFYING_YEARS: int = 1

#: Said on a settlement whose gratuity is payable only because the fixed term has expired (fewer than five years).
FIXED_TERM_BASIS = (
    "Fixed-term employment that has expired: gratuity is payable on at least one year of service under the contract, not five, pro rata "
    "to the service rendered, and a part of a year over six months counts as a year (the second proviso to section 53(1) and the third "
    "proviso to section 53(2) of the Code on Social Security, 2020, and rule 33(1)(a) of the Social Security (Central) Rules, 2026). "
    "Service is counted from the joining date and taken as service under the one contract. The amount is the same formula over the "
    "years of the contract; whether the contract gives more is not considered."
)

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
    #: The employee is recorded as being on fixed-term employment (POST-A-526). Whether it changed the service the entitlement needs
    #: depends on `fixed_term_expired`: only the expiry of the term waives the five years.
    fixed_term: bool = False
    fixed_term_expired: bool = False
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


def fixed_term_has_expired(end_date: date | None, on: date | None) -> bool:
    """The contract's RECORDED end date has been reached on `on`.

    No recorded end date, or no date to compare with, is "not known to have expired", never "expired": the CA states the expiry when
    the settlement is recorded, and a short service or a leaving date never decides it (POST-A-526).
    """
    return bool(end_date and on and on >= end_date)


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
    fixed_term: bool = False,
    fixed_term_expired: bool = False,
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
            "Gratuity is computed here on basic and dearness allowance, the "
            "wages of the repealed Payment of Gratuity Act, 1972 (the Code's own "
            "definition of wages, section 2(88), is not applied: owner list S50), "
            "excluding bonus, commission, HRA and overtime. No basic or DA is "
            "recorded for this employee."
        )
        return out

    # §4(1): five years, unless death or disablement; where a fixed term EXPIRES, one year under the contract (POST-A-526).
    out.fixed_term = bool(fixed_term)
    out.fixed_term_expired = bool(fixed_term and fixed_term_expired)
    needed = FIXED_TERM_QUALIFYING_YEARS if out.fixed_term_expired else QUALIFYING_YEARS
    if years < needed and not on_death_or_disablement:
        if out.fixed_term_expired:
            out.reasons.append(
                f"{years} completed year{'' if years == 1 else 's'} of service under the contract. The fixed term has expired, "
                f"and a fixed-term employee is eligible once service under the contract is at least one year (the second "
                f"proviso to section 53(1) of the Code on Social Security, 2020; rule 33(1)(a) of the Social Security (Central) "
                f"Rules, 2026), which this is not."
            )
        elif fixed_term:
            out.reasons.append(
                f"{years} completed year{'' if years == 1 else 's'} of service. This employee is recorded as on fixed-term "
                f"employment, but section 53(1) waives the five years only where the employment ends by the expiry of the "
                f"fixed term (its second proviso), and nothing here says the term has expired. A fixed-term employee who "
                f"resigns or is dismissed before the term ends is not shown as eligible on one year: rule 33(1)(a) names one "
                f"year under the contract without naming expiry, and the text read does not say how the two fit (owner list "
                f"S50). If the term has expired, say so when the settlement is recorded."
            )
        else:
            out.reasons.append(
                f"{years} completed year{'' if years == 1 else 's'} of service. Section "
                f"53(1) of the Code on Social Security, 2020 requires five, and the "
                f"exception for death or disablement does not apply here."
            )
        return out

    out.eligible = True
    if out.fixed_term_expired and years < QUALIFYING_YEARS and not on_death_or_disablement:
        # payable only by the fixed-term provisions: say so, because a CA reading five years in the module would otherwise refuse it
        out.gaps.append(FIXED_TERM_BASIS)

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
                "This employee is recorded as not covered by gratuity (the "
                "repealed Payment of Gratuity Act, 1972, now section 53 of the "
                "Code on Social Security, 2020), so IT Act §10(10)(iii) applies: "
                "the exemption is half a month's AVERAGE "
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
            f"{rupee_text(paid)} is being paid against a statutory entitlement of "
            f"{rupee_text(statutory)}. §10(10) exempts the FORMULA amount, not "
            f"whatever was paid, so the excess is taxable salary and belongs in "
            f"the year's §17(1) figure."
        )

    return out
