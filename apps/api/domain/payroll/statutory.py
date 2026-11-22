"""
TODO(compliance): docs/compliance/04-mca-epfo-esic.md
    (1) The Rs 500 A/c-2 minimum was set when the admin charge was 0.65%.
        Neither this module nor the Sept 2026 research has a primary source
        confirming it survived the cut to 0.50% on 01-06-2018. Both assert
        Rs 500 — that is agreement, not verification.

    (2) THE PF WAGE BASE MOVED ON 21-11-2025, AND IS NOW HANDLED. The Code on
        Social Security subsumed the EPF Act and adopts its own definition of wages
        (s.2(88)): exclusions capped at half of total remuneration,
        excess deemed wages. domain/payroll/wage_base.py implements it,
        migration 334 stores the working on the slip, and the RATES below are
        unaffected; it was only the BASE they apply to that moved. The wage
        CEILING moved too, later and for a different reason: it is notified, and
        became Rs 25,000 on 17-09-2026 (PF_WAGE_CEILINGS, POST-A-516).

        ESI may err the OTHER way — _compute_esi uses gross, and the Code's
        definition is narrower — but that is UNCONFIRMED and deliberately NOT
        changed. Gratuity is computed on "wages" too and is likewise untouched.
        Both are pinned by tests so a later change is a deliberate act.

Payroll statutory rates and ceilings, versioned by financial year.

WHY THIS MODULE EXISTS

routers/payroll.py carried these as bare literals — min(pf_wages_paise, 1500000)
for the EPF ceiling, gross_paise > 2100000 for ESI, and the professional tax
slabs inline. CLAUDE.md's annual-maintenance checklist records that as a known
gap: they change by EPFO / ESIC / state notification, they cannot be printed by
the coverage command every other registry answers to, and so they can only be
found by reading the code. This gives them the same shape as
domain/income_tax/statutory_rates.py and the rest.

THE FALLBACK IS THE SAME, AND SO IS ITS DANGER

rates_for() returns LATEST_VERIFIED_FY's values for a year it does not hold, so
a missing year is a confidently wrong number rather than an error. That is the
convention across every registry here; it is written down in CLAUDE.md and it
is why the annual sweep is a checklist somebody works.

WHAT THE EMPLOYER'S 12% ACTUALLY IS

Not one number. The Employees' Provident Funds Scheme, 2026 (para 18) sets the
employee's contribution at 12% of the wages and the employer matches it — but
the Employees' Pension Scheme, 2026 (para 4(1)) diverts part of the EMPLOYER's
share to the pension fund:

    EPS  = 8.33% of PF wages up to the notified wage ceiling
           (1,250 at Rs 15,000, 2,083 at Rs 25,000)
    EPF  = the employer's 12% MINUS whatever went to EPS

so at or below the ceiling the employer's share is 8.33% pension + 3.67% PF, and
above it the EPS amount stops rising while the EPF half absorbs the rest. The
employee's own 12% is never split — all of it is EPF.

Two further employer costs sit OUTSIDE the 12% and are not deducted from anyone:

    EDLI   0.5% of PF wages up to the notified ceiling (at most 75 at Rs 15,000,
           125 at Rs 25,000); the rate is "as notified" (owner list S49)
    admin  0.5% of PF wages, subject to a MINIMUM PER ESTABLISHMENT of 500 a
           month, which is why it cannot be finally settled on one payslip;
           per-employee 0.5% is computed here and the floor is applied when the
           run is totalled. EDLI admin charges have been nil since 01-04-2017.

Getting this split wrong is not only a wrong trial balance. The EPFO's ECR file
carries EPF wages, EPS wages, the EPF contribution, the EPS contribution and the
difference between them as separate columns per member, so a flat 12% cannot
produce a valid return at all.
"""
from __future__ import annotations

import calendar
from dataclasses import dataclass, replace
from datetime import date

from domain.money_sentence import rupee_whole_text


@dataclass(frozen=True)
class PFRates:
    """The Employees' Provident Funds, Pension and Deposit-Linked Insurance Schemes, 2026 (replacing the 1952, 1995 and 1976 schemes)."""
    wage_ceiling_paise: int          # the notified ceiling at the year's FIRST day; a month is resolved by pf_rates_for_month
    employee_rate_bps: int           # 12% = 1200 bps, all to EPF
    employer_rate_bps: int           # 12% total employer share
    eps_rate_bps: int                # 8.33% of PF wages, out of the employer's 12%
    eps_ceiling_paise: int           # the employer's EPS wages: the same notified ceiling (pension scheme 2026 para 4(1))
    edli_rate_bps: int               # 0.5%
    edli_ceiling_paise: int          # EDLI wages: the same notified ceiling (insurance scheme 2026 para 5(1))
    admin_rate_bps: int              # 0.5%
    admin_minimum_paise: int         # 500 per ESTABLISHMENT per month


@dataclass(frozen=True)
class ESIRates:
    """ESI Act 1948 §2(9); rates from Notification of 13-06-2019."""
    wage_ceiling_paise: int          # 21,000 — gross ABOVE this is out of ESI
    employee_rate_bps: int           # 0.75%
    employer_rate_bps: int           # 3.25%


@dataclass(frozen=True)
class PayrollRates:
    fy: str
    pf: PFRates
    esi: ESIRates


# ── THE WAGE CEILING MOVES BY NOTIFICATION, NOT BY FINANCIAL YEAR (POST-A-516) ─────────────────────────────────────────────────
#
# Until 29-06-2026 each of the three provident fund schemes stated Rs 15,000 in its own text (EPF Scheme 1952 para 26, Pension Scheme
# 1995 para 3, Insurance Scheme 1976 para 7). The Employees' Provident Funds Scheme, 2026, the Employees' Pension Scheme, 2026 and the
# Employees' Deposit-Linked Insurance Scheme, 2026 (G.S.R. 525(E), 527(E), 526(E) of 29-06-2026, read from the Gazette on 19-11-2026)
# state NO figure: each ties its contribution to the wage ceiling the Central Government notifies (provident fund para 18(3), the
# employer's pension share para 4(1) with the first proviso to 4(2), insurance para 5(1) "subject to the wage ceiling specified in
# clause (89) of section 2 of the Code"). So the ceiling for EPF wages, the employer's EPS wages and EDLI wages is ONE figure, and it
# changes on the day a notification takes effect, which is not an April 1.
#
# The Central Government's own 1.16% pension contribution is limited to Rs 15,000 by G.S.R. 890(E) (in force 17-09-2026). It is a
# different thing, is not the employer's and is posted by nobody here.
#
# `verified` is the grade the notes use: True where the primary text was read.
@dataclass(frozen=True)
class WageCeilingNotification:
    effective_from: date
    ceiling_paise: int
    source: str
    verified: bool


PF_WAGE_CEILINGS: tuple[WageCeilingNotification, ...] = (
    WageCeilingNotification(
        effective_from=date(2014, 9, 1),
        ceiling_paise=15_000_00,
        source=("Rs 15,000: the old schemes' own text (read from EPFO's published copies on 19-11-2026), carried by S.O. 2702(E) of "
                "29-05-2026, the first notification under section 2(89) of the Code, whose figure is known from secondary reports only"),
        verified=False,
    ),
    WageCeilingNotification(
        effective_from=date(2026, 9, 17),
        ceiling_paise=25_000_00,
        source=("S.O. 5109(E) of 17-09-2026 under section 2(89) of the Code on Social Security, 2020: \"rupees twenty-five thousand "
                "(Rs 25,000) per month as the wage ceiling for the purposes of Chapter III ... with effect from the date of publication\" "
                "(the e-Gazette's own copy, No. 4918, read on 19-11-2026)"),
        verified=True,
    ),
)


@dataclass(frozen=True)
class CeilingForMonth:
    """The ceiling a wage month is computed on, and whether a notification took effect INSIDE it."""
    ceiling_paise: int
    #: A notification took effect after the month began and on or before its last day. The texts read give no rule for such a month
    #: (the Schemes say contributions are on wages "actually drawn or payable during the month" and subject to the ceiling "notified
    #: ... from time to time"), so the ceiling at the START of the month is used and the month is NAMED, never settled by a guess.
    straddles: bool
    effective_from: date | None
    note: str | None


def _ceiling_in_force_on(day: date) -> WageCeilingNotification:
    in_force = [n for n in PF_WAGE_CEILINGS if n.effective_from <= day]
    return in_force[-1] if in_force else PF_WAGE_CEILINGS[0]


def wage_ceiling_for_month(year: int, month: int) -> CeilingForMonth:
    """The provident fund / pension / insurance wage ceiling for the calendar month (year, month)."""
    first = date(year, month, 1)
    last = date(year, month, calendar.monthrange(year, month)[1])
    at_start = _ceiling_in_force_on(first)
    inside = [n for n in PF_WAGE_CEILINGS if first < n.effective_from <= last]
    if not inside:
        return CeilingForMonth(at_start.ceiling_paise, False, None, None)
    change = inside[-1]
    note = (f"The wage ceiling was notified at {rupee_whole_text(change.ceiling_paise, 'Rs ')} from {change.effective_from.strftime('%d-%m-%Y')} "
            f"(S.O. 5109(E)), in the middle of this wage month, and no text read says which ceiling applies to a month the change falls "
            f"in. This month uses {rupee_whole_text(at_start.ceiling_paise, 'Rs ')}, the ceiling at its start; confirm the treatment before filing.")
    return CeilingForMonth(at_start.ceiling_paise, True, change.effective_from, note)


def wage_month_of(fy: str | None, month: int | None) -> tuple[int, int] | None:
    """(calendar year, calendar month) of month number `month` (1-12) inside the financial-year label `fy`, or None when either is unknown.

    April to December belong to the label's first year, January to March to its second: "2026-27" month 10 is October 2026.
    """
    if not fy or month is None or not 1 <= int(month) <= 12:
        return None
    try:
        start = int(fy[:4])
    except (ValueError, TypeError):
        # A label that does not start with a year: unknown (docstring), never a guessed wage month.
        return None
    return (start if int(month) >= 4 else start + 1, int(month))


_FY_2025_26 = PayrollRates(
    fy="2025-26",
    pf=PFRates(
        # The three ceilings are read from the notification table at the year's FIRST day, so the table is the only authority; a
        # month inside the year is resolved by pf_rates_for_month.
        wage_ceiling_paise=_ceiling_in_force_on(date(2025, 4, 1)).ceiling_paise,
        employee_rate_bps=1200,
        employer_rate_bps=1200,
        eps_rate_bps=833,
        eps_ceiling_paise=_ceiling_in_force_on(date(2025, 4, 1)).ceiling_paise,
        edli_rate_bps=50,
        edli_ceiling_paise=_ceiling_in_force_on(date(2025, 4, 1)).ceiling_paise,
        admin_rate_bps=50,
        admin_minimum_paise=500_00,
    ),
    esi=ESIRates(
        wage_ceiling_paise=21_000_00,
        employee_rate_bps=75,
        employer_rate_bps=325,
    ),
)

# 2026-27 carries 2025-26's figures because no EPFO or ESIC notification has
# changed them. It is a SEPARATE entry rather than a fallback so that the
# coverage command reports the year as present, and so that changing one year
# cannot silently move another.
_FY_2026_27 = PayrollRates(
    fy="2026-27",
    pf=replace(
        _FY_2025_26.pf,
        wage_ceiling_paise=_ceiling_in_force_on(date(2026, 4, 1)).ceiling_paise,
        eps_ceiling_paise=_ceiling_in_force_on(date(2026, 4, 1)).ceiling_paise,
        edli_ceiling_paise=_ceiling_in_force_on(date(2026, 4, 1)).ceiling_paise,
    ),
    esi=_FY_2025_26.esi,
)

RATES_BY_FY: dict[str, PayrollRates] = {
    "2025-26": _FY_2025_26,
    "2026-27": _FY_2026_27,
}

# The last year a human checked these against the EPFO / ESIC notifications.
LATEST_VERIFIED_FY = "2026-27"


def esi_contribution_period(month: str) -> str:
    """The ESI contribution period a "YYYY-MM" payroll month falls in.

    ESI Rule 50 runs two six-month periods, April-September and October-March,
    and they matter for more than reporting: an employee whose wages rise above
    the ceiling PART WAY THROUGH a period does not leave the scheme then. They
    remain an employee, and contributions continue on their actual wages, until
    that period ends. Someone on 20,500 in April who is raised to 24,000 in May
    contributes until September and leaves in October.

    Returns a label like "2026-H1" (April-September 2026) or "2026-H2"
    (October 2026 - March 2027). The label carries the year the period STARTED,
    so October to March is one period rather than two.
    """
    y, m = int(month[:4]), int(month[5:7])
    if 4 <= m <= 9:
        return f"{y}-H1"
    return f"{y}-H2" if m >= 10 else f"{y - 1}-H2"


def rates_for(fy: str | None = None) -> PayrollRates:
    """Rates for an FY string ("2025-26"), falling back to the latest verified.

    Same convention — and the same hazard — as every other registry here: an
    unknown year returns last year's numbers rather than raising. See CLAUDE.md.
    """
    from domain.income_tax.statutory_rates import current_fy
    fy = fy or current_fy()
    if fy in RATES_BY_FY:
        return RATES_BY_FY[fy]
    return RATES_BY_FY[LATEST_VERIFIED_FY]


def pf_rates_for_month(fy: str | None, month: int | None) -> PFRates:
    """The provident fund rates for a wage month: the year's figures with the three ceilings read at that MONTH.

    `month` is the calendar month number (1-12) inside the financial-year label `fy`. Where either is unknown the year's own figures are
    returned, which is what every caller did before the ceiling could move inside a year.
    """
    base = rates_for(fy).pf
    ym = wage_month_of(fy, month)
    if ym is None:
        return base
    c = wage_ceiling_for_month(*ym).ceiling_paise
    return replace(base, wage_ceiling_paise=c, eps_ceiling_paise=c, edli_ceiling_paise=c)


def wage_ceiling_gap(fy: str | None, month: int | None) -> str | None:
    """The sentence for a wage month a ceiling change falls inside, or None. Names the month; settles nothing."""
    ym = wage_month_of(fy, month)
    if ym is None:
        return None
    return wage_ceiling_for_month(*ym).note


def admin_charge_for_establishment(per_member_total_paise: int,
                                   fy: str | None = None) -> int:
    """The EPF administrative charge an ESTABLISHMENT owes for a month.

    The 0.5% is computed per member, but the charge carries a statutory MINIMUM
    of ₹500 per establishment per month — not per member — so the figure that is
    actually owed can only be settled on the run total. Three members at ₹60
    each owe ₹500, not ₹180.

    That is why it lives here rather than in _compute_pf: a per-payslip function
    cannot see the establishment, and a caller that simply added up payslips
    would under-state the charge for every small client.

    A run with NO members owes nothing — the floor applies to an establishment
    that is contributing, not to one with no payroll at all. Returning ₹500 for
    an empty run would invent a liability out of a month in which nobody was
    employed.
    """
    total = int(per_member_total_paise or 0)
    if total <= 0:
        return 0
    return max(total, rates_for(fy).pf.admin_minimum_paise)
