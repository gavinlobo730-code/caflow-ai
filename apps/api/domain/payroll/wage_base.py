"""The s.2(y) wage base, and the 50% rule that can add allowances back into it.

WHAT THIS IS FOR

    Until 21 November 2025 the PF wage base was, in the code and in the world,
    `basic + DA` — EPF Act s.2(b) and s.6. The four Labour Codes commenced that
    day, the Code on Social Security 2020 subsumed the EPF Act 1952, and it
    adopts the Code on Wages definition of "wages" for computing provident fund.

    That definition is s.2(y) of the Code on Wages 2019: all remuneration, minus
    a listed set of exclusions, with a proviso that caps the exclusions at half
    of total remuneration and DEEMS the excess to be wages.

        wages = (total remuneration - exclusions) + max(0, exclusions - 50%)

    It is best read as A CAP ON EXCLUSIONS, NOT A FLOOR UNDER BASIC. It does not
    require basic to be 50% of CTC; it adds back whatever excess there is.

    Verified 2026-09-04 (docs/compliance/04-mca-epfo-esic.md), including
    searches for a deferral or transitional relief — none. The Code on Social
    Security rules were notified 08-05-2026 and a Ministry notification of
    29-05-2026 re-declared Rs 15,000 as the Chapter III wage ceiling under the
    new Code, so the framework is operative rather than pending.

WHY THE CEILING MEANS THIS IS NARROWER THAN IT SOUNDS

    The Rs 15,000 EPF ceiling is unchanged. For anyone whose basic + DA already
    reaches it, `min(wages, 15000)` makes the add-back irrelevant and the old
    figure was already right. The exposure is employees BELOW the ceiling on a
    low-basic / high-allowance structure — which is the ordinary Indian salary
    structure at exactly those salary levels.

    Worked: total 28,000 as 10,000 basic + 18,000 HRA. Exclusions are 64% of
    total; half is 14,000; the 4,000 excess is deemed wages; wages are 14,000
    rather than 10,000, and employee PF at 12% is 1,680 rather than 1,200 —
    480 a month understated on each side, in somebody's own provident fund.

WHICH COMPONENTS ARE EXCLUDED, AND THE ONE RULE FOR DECIDING

    s.2(y) excludes, at (a) to (k): a statutory bonus not forming part of
    contractual remuneration; the value of house accommodation, light, water,
    medical attendance or other amenity excluded BY GOVERNMENT ORDER; the
    employer's PF/pension contribution and interest on it; conveyance allowance
    or the value of a travelling concession; a sum paid to defray special
    expenses entailed by the nature of the employment; house rent allowance;
    remuneration under an award or settlement; overtime; commission; gratuity on
    termination; and retrenchment compensation, other retirement benefit or ex
    gratia on termination.

    THE 50% CAP APPLIES TO (a) TO (i). Gratuity (j) and retrenchment
    compensation (k) are ring-fenced and never add back — they are exit
    payments, and folding them into a monthly wage test would be nonsense.

    Of the components this product models, exactly TWO are named by the statute
    closely enough to classify without judgement:

        HRA  -> clause (f), "house rent allowance", verbatim
        LTA  -> clause (d), "the value of any travelling concession"

    Everything else defaults to WAGES, and that default is deliberate rather
    than lazy. Two reasons:

      * It is the direction that CANNOT UNDER-DEDUCT. Misclassifying a wage
        component as excluded under-states the base and short-credits an
        employee's provident fund; misclassifying an excluded component as a
        wage over-states it. Only one of those wrongs an employee, and only one
        of them draws s.7Q interest and s.14B damages.
      * The two obvious candidates do not survive reading the clauses. A cash
        MEDICAL ALLOWANCE is not clause (b), which is about amenities in kind
        excluded by a government order. A SPECIAL ALLOWANCE is not clause (e),
        which is about defraying expenses actually entailed by the job, not a
        residual balancing figure — and *RPFC v. Vivekananda Vidyamandir* (2019)
        held allowances paid universally to all employees to be basic wages.

    So a component this module has never heard of is treated as a wage. Adding
    a new EXCLUDED component is a deliberate act requiring a clause to cite.

WHAT IS DELIBERATELY OUT OF THE TEST

    ONE-TIME AND VARIABLE EARNINGS. They are not in total remuneration for this
    purpose, and leaving them out is the conservative choice both ways: a bonus
    is excluded at (a) and a commission at (i), so they would be exclusions
    rather than wages — but including them in the DENOMINATOR would raise the
    50% half and SHRINK the add-back, which is the direction that under-deducts.
    The monthly test is about the recurring structure. Arrears of basic and DA
    still reach the PF base the way they always did, added after this function.

    ESI. `_compute_esi` takes gross, which was right under ESI Act s.2(9) where
    "wages" was already broad. Under the Code the ESI base would be this
    narrower figure, i.e. generally LESS than gross — so ESI may be over-stated
    where PF was under-stated, the opposite direction. That is UNCONFIRMED, and
    changing it on an unconfirmed reading would move money the other way. Not
    touched here.

    GRATUITY. Computed on "wages" too, so the same redefinition reaches it.
    Out of scope of this change and unverified.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date

# The four Labour Codes commenced on this day. A payroll month ENDING before it
# is computed on the old EPF Act s.2(b) basis; a month ending on or after it
# uses s.2(y). Verified 2026-09-04.
WAGE_RULE_EFFECTIVE_FROM = date(2025, 11, 21)

# The proviso's cap, in basis points of total remuneration, so the arithmetic
# stays integral. 50% == 5000 bps. It is expressed as a constant because the
# Code lets the appropriate Government notify a different percentage.
EXCLUSION_CAP_BPS = 5000


@dataclass(frozen=True)
class WageBase:
    """The s.2(y) wage figure for one employee for one month, and its working.

    Every field is kept because a CA reconciling a challan needs to see WHY the
    base differs from basic + DA, not just that it does.
    """
    wages_paise: int
    total_remuneration_paise: int
    excluded_paise: int
    deemed_addback_paise: int
    rule_applied: bool

    @property
    def addback_applies(self) -> bool:
        return self.deemed_addback_paise > 0


def _last_day_of(fy_label: str, month: int) -> date:
    """The last day of calendar `month` within `fy_label`.

    The financial year runs April to March, so months 4-12 fall in the label's
    first calendar year and months 1-3 in its second. Used only to decide which
    side of 21-11-2025 a payroll month sits on.
    """
    start_year = int(str(fy_label).split("-")[0])
    year = start_year if month >= 4 else start_year + 1
    return date(year, month, calendar.monthrange(year, month)[1])


def rule_in_force(fy_label: str | None, month: int | None) -> bool:
    """Whether s.2(y) governs the PF base for this payroll month.

    Unknown period -> False. That is the pre-Code behaviour, and it is the
    right default for a caller that cannot say which month it is computing:
    silently applying a rule to a period it may not govern would rewrite
    historic payslips.

    The test is on the month END rather than its start, so November 2025 —
    the month the Codes commenced part-way through — is treated as governed.
    A month is paid as one thing; splitting it at the 21st would produce a
    wage base for a fortnight, which no return has a column for.
    """
    if not fy_label or not month:
        return False
    try:
        month = int(month)
        if not 1 <= month <= 12:
            return False
        return _last_day_of(fy_label, month) >= WAGE_RULE_EFFECTIVE_FROM
    except (ValueError, TypeError, IndexError):
        return False


def compute(
    *,
    wage_components_paise: int,
    excluded_components_paise: int,
    fy_label: str | None = None,
    month: int | None = None,
) -> WageBase:
    """The s.2(y) wage base for one month.

    `wage_components_paise` is everything that is remuneration and NOT in the
    exclusion list — basic, DA, and by the default above anything unclassified.
    `excluded_components_paise` is the clause (a)-(i) total: here, HRA and LTA.

    Before 21-11-2025 the exclusions are simply left out and no add-back
    happens, which reproduces the old `basic + DA` exactly.
    """
    wage_components_paise = max(0, int(wage_components_paise or 0))
    excluded_components_paise = max(0, int(excluded_components_paise or 0))
    total = wage_components_paise + excluded_components_paise

    if not rule_in_force(fy_label, month):
        return WageBase(
            wages_paise=wage_components_paise,
            total_remuneration_paise=total,
            excluded_paise=excluded_components_paise,
            deemed_addback_paise=0,
            rule_applied=False,
        )

    # Integer arithmetic throughout (CLAUDE.md: never floating point for money).
    # The half is floored, which resolves an odd-paise total in the direction of
    # a LARGER add-back — the direction that cannot under-deduct.
    cap = (total * EXCLUSION_CAP_BPS) // 10000
    addback = max(0, excluded_components_paise - cap)
    return WageBase(
        wages_paise=wage_components_paise + addback,
        total_remuneration_paise=total,
        excluded_paise=excluded_components_paise,
        deemed_addback_paise=addback,
        rule_applied=True,
    )
