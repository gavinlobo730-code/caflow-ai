"""
Statutory bonus — Payment of Bonus Act 1965.

WHAT THE ACT ACTUALLY REQUIRES

Bonus under this Act is not a discretionary payment. Where the Act applies it is
a debt, payable within eight months of the accounting year's close (§19), at a
minimum of 8.33% of the year's salary whether or not the employer made a profit
(§10). Only the amount ABOVE that minimum depends on the allocable surplus.

  §2(13)  An "employee" is one drawing salary or wage NOT EXCEEDING ₹21,000 a
          month. Above that the Act simply does not apply — the employer may pay
          an ex gratia, but it is not statutory bonus and is not computed here.
          (₹10,000 until the Payment of Bonus (Amendment) Act 2015 raised it,
          with retrospective effect from 01-04-2014.)

  §2(21)  "Salary or wage" is basic plus dearness allowance. It excludes HRA,
          overtime, commission and every other allowance — the same shape as
          the gratuity definition, and for the same reason.

  §8      Eligibility needs THIRTY WORKING DAYS in the accounting year. Not
          thirty calendar days, and not a proportion of the year.

  §10     Minimum bonus: 8.33% of the salary earned in the year, or ₹100,
          whichever is higher (₹60 for an employee under fifteen at the start of
          the year). Payable "whether or not the employer has any allocable
          surplus in the accounting year".

  §11     Maximum bonus: 20%, where the allocable surplus exceeds the minimum.

  §12     THE CALCULATION CEILING, and the part most often got wrong. Where
          salary exceeds ₹7,000 per month "or the minimum wage for the scheduled
          employment, as fixed by the appropriate Government, WHICHEVER IS
          HIGHER", the bonus is computed as if the salary were that higher
          figure. So ₹7,000 is a floor on the ceiling, not the ceiling itself:
          in a state whose minimum wage for the employment is ₹11,000, the
          calculation base is ₹11,000, and using ₹7,000 underpays by a third.

  §9      Disqualification — dismissal for fraud, riotous or violent behaviour
          on the premises, or theft, misappropriation or sabotage of the
          establishment's property. Note it is DISMISSAL for those causes, not
          the conduct alone, and it forfeits the whole bonus.

WHY THE MINIMUM WAGE IS AN INPUT AND NOT A TABLE

§12's comparison is against the minimum wage "for the scheduled employment" as
fixed by "the appropriate Government" — which varies by state, by scheduled
employment, by skill category, and is revised twice yearly in most states. There
is no single number and there never will be. Supplying it is a human step, like
the professional tax slabs; where it is absent this module computes on ₹7,000
and SAYS it did, rather than presenting a figure that silently assumes ₹7,000 is
the higher of the two.

WHY BONUS IS NOT TAX-EXEMPT

There is no exemption. Bonus is salary under §17(1) and is taxable in the year
of RECEIPT — which is why a bonus for FY 2024-25 paid in November 2025 belongs
in FY 2025-26's Form 16, not in the year it was earned. This module returns the
accounting year it relates to alongside the amount, so that distinction survives
into the payroll that pays it.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from dataclasses import dataclass, field

# §2(13) — the eligibility ceiling. Above this the Act does not apply at all.
ELIGIBILITY_CEILING_PAISE: int = 21_000 * 100

# §12 — the floor on the calculation ceiling, raised from ₹3,500 by the 2015
# amendment. The actual ceiling is the HIGHER of this and the minimum wage.
CALCULATION_FLOOR_PAISE: int = 7_000 * 100

# §10 / §11 — the statutory band, in basis points of the year's salary.
MINIMUM_RATE_BPS: int = 833          # 8.33%
MAXIMUM_RATE_BPS: int = 2000         # 20%

# §10 — the absolute floor in rupees, whichever is higher than the percentage.
MINIMUM_BONUS_PAISE: int = 100 * 100
MINIMUM_BONUS_UNDER_15_PAISE: int = 60 * 100

# §8 — thirty WORKING days in the accounting year.
QUALIFYING_WORKING_DAYS: int = 30


@dataclass
class BonusResult:
    accounting_year: str = ""
    payable_paise: int = 0
    minimum_paise: int = 0
    maximum_paise: int = 0
    calculation_base_monthly_paise: int = 0
    months_counted: int = 0
    eligible: bool = False
    reasons: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)


def compute(
    *,
    accounting_year: str,
    monthly_salary_paise: int,
    months_worked: int,
    working_days_in_year: int,
    rate_bps: int = MINIMUM_RATE_BPS,
    minimum_wage_monthly_paise: int | None = None,
    under_fifteen: bool = False,
    disqualified_under_section_9: bool = False,
) -> BonusResult:
    """Statutory bonus for one employee for one accounting year.

    `monthly_salary_paise` is §2(21) salary — basic plus DA, nothing else.
    `rate_bps` is where the employer's allocable surplus lands them between the
    §10 minimum and the §11 maximum; it is the employer's determination from
    their own accounts, not something payroll can derive, so it is an input that
    defaults to the statutory minimum.
    """
    out = BonusResult(accounting_year=accounting_year)

    if monthly_salary_paise <= 0:
        out.reasons.append(
            "No basic or DA is recorded. §2(21) defines salary or wage for this "
            "Act as basic plus dearness allowance, so there is nothing to compute "
            "on."
        )
        return out

    # §2(13) — the Act applies only up to ₹21,000 a month.
    if monthly_salary_paise > ELIGIBILITY_CEILING_PAISE:
        out.reasons.append(
            f"Salary of ₹{monthly_salary_paise / 100:,.2f} a month exceeds the "
            f"₹21,000 ceiling in §2(13), so this Act does not apply. An employer "
            f"may still pay an ex gratia, but it is not statutory bonus and is "
            f"not computed here."
        )
        return out

    # §9 — dismissal for fraud, violence, theft, misappropriation or sabotage.
    if disqualified_under_section_9:
        out.reasons.append(
            "Disqualified under §9. Dismissal for fraud, riotous or violent "
            "behaviour on the premises, or theft, misappropriation or sabotage "
            "forfeits the whole bonus — not a part of it."
        )
        return out

    # §8 — thirty WORKING days, not thirty calendar days.
    if working_days_in_year < QUALIFYING_WORKING_DAYS:
        out.reasons.append(
            f"{working_days_in_year} working days in the year. §8 requires thirty "
            f"before any bonus is payable."
        )
        return out

    out.eligible = True

    # §12 — the calculation base is the HIGHER of ₹7,000 and the minimum wage,
    # but never more than the salary actually drawn.
    if minimum_wage_monthly_paise is None:
        base_ceiling = CALCULATION_FLOOR_PAISE
        out.gaps.append(
            "§12 computes bonus on ₹7,000 a month OR the minimum wage for the "
            "scheduled employment, WHICHEVER IS HIGHER. No minimum wage is "
            "supplied, so ₹7,000 was used. Where the state's minimum wage for "
            "this employment is higher — and in most states for most scheduled "
            "employments it is — this figure is too low."
        )
    else:
        base_ceiling = max(CALCULATION_FLOOR_PAISE, max(0, minimum_wage_monthly_paise))

    base = min(monthly_salary_paise, base_ceiling)
    out.calculation_base_monthly_paise = base

    months = max(0, min(12, int(months_worked)))
    out.months_counted = months
    salary_for_year = base * months

    # §10 and §11.
    out.minimum_paise = max(
        salary_for_year * MINIMUM_RATE_BPS // 10000,
        MINIMUM_BONUS_UNDER_15_PAISE if under_fifteen else MINIMUM_BONUS_PAISE,
    )
    out.maximum_paise = salary_for_year * MAXIMUM_RATE_BPS // 10000

    rate = max(MINIMUM_RATE_BPS, min(MAXIMUM_RATE_BPS, int(rate_bps)))
    if rate != rate_bps:
        out.gaps.append(
            f"A rate of {rate_bps / 100:.2f}% was asked for; §10 and §11 confine "
            f"bonus to between 8.33% and 20%, so {rate / 100:.2f}% was used."
        )
    at_rate = salary_for_year * rate // 10000
    out.payable_paise = min(max(at_rate, out.minimum_paise), out.maximum_paise)

    return out
