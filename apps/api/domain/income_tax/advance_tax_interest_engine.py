"""
Advance tax interest computation — IT Act 1961 Section 234C (interest for
deferment of advance tax) and Section 207/208 (advance-tax liability and
the four-instalment schedule).

R3.13a (fixes a live correctness bug): apps/web/app/income-tax/advance-tax/
page.tsx's compute234CInterest() computed interest as a function of the
*actual* number of days between an instalment's due date and whenever it
was actually paid — that is the Section 234B ("interest for default in
payment") shape, not Section 234C's. Section 234C instead prescribes a
FIXED interest period per instalment (3 months for instalments 1-3, 1
month for instalment 4) regardless of how late the payment actually was,
and additionally gives instalments 1 and 2 a "trigger" tolerance below
their headline cumulative requirement (12% vs. the 15% due by 15 Jun; 36%
vs. the 45% due by 15 Sep) under which no interest applies for that
instalment at all, even though the cumulative amount paid is technically
short of the full-year target. Neither the fixed-period structure nor the
trigger tolerance existed in the old client-side formula, which also used
today's date (not the instalment's own due date) for anything not yet
marked paid.

This module treats Section 234C's numeric structure (the 12/36/75/100
percent thresholds, the 3/3/3/1 month periods, and the 1%-per-month rate)
as settled, long-standing statutory text — not an annually-revised rate
table — and implements it directly, the same way capital_gains_engine.py
implements Section 111A/112A/50AA/115BBH's rates directly rather than
flagging them "pending verification" (that discipline is reserved for
empirical data that changes by government notification, like the CII table
or state Professional Tax slabs — see roadmap R3.1/R3.12).

KNOWN SIMPLIFICATION: Section 234C(1)'s proviso exempts the shortfall
caused by income that could not reasonably have been foreseen (capital
gains, casual/lottery income, and certain dividend income) from interest
for the instalments preceding when that income arose. This engine has no
per-income-type breakdown to evaluate that proviso — the existing UI (and
the `advance_tax_payments` table) only ever collected one lump "estimated
annual tax" figure per instalment — and does not attempt it. Not
implemented rather than silently assumed; a future extension needing
quarter-wise income-head detail is out of scope here.

Integer paise throughout — never float in any stored or returned amount.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional


def _round_paise(numerator: int, denominator: int) -> int:
    """Integer round-half-up division — never a float intermediate."""
    if denominator == 0:
        return 0
    half = denominator // 2
    if numerator >= 0:
        return (numerator + half) // denominator
    return -((-numerator + half) // denominator)


@dataclass(frozen=True)
class InstallmentRule:
    number: int
    cumulative_required_percent: int  # % of estimated annual tax due by this date — Section 208
    trigger_percent: int              # % below which Section 234C interest applies for this instalment
    interest_months: int              # fixed period Section 234C charges, regardless of actual payment date


# Section 208 instalment schedule — applies uniformly to all assessees
# other than those under presumptive taxation u/s 44AD/44ADA (out of scope
# here; they have a single 15 Mar/100% instalment with no interim
# instalments), since the Finance Act 2016 amendment aligned the
# corporate and non-corporate schedules onto the same 15/45/75/100 split.
#
# Section 234C(1)'s trigger tolerance: instalments 1 and 2 only need to
# clear 12%/36% (not the full 15%/45%) to avoid interest for THAT
# instalment; instalments 3 and 4 have no such tolerance — the trigger IS
# the full cumulative requirement.
INSTALLMENT_RULES: tuple[InstallmentRule, ...] = (
    InstallmentRule(number=1, cumulative_required_percent=15, trigger_percent=12, interest_months=3),
    InstallmentRule(number=2, cumulative_required_percent=45, trigger_percent=36, interest_months=3),
    InstallmentRule(number=3, cumulative_required_percent=75, trigger_percent=75, interest_months=3),
    InstallmentRule(number=4, cumulative_required_percent=100, trigger_percent=100, interest_months=1),
)

_INTEREST_RATE_PERCENT_PER_MONTH = 1


def installment_schedule(fy: str) -> list[tuple[int, date]]:
    """Section 208 due dates for a given FY string e.g. '2025-26'."""
    start_year = int(fy.split("-")[0])
    return [
        (1, date(start_year, 6, 15)),
        (2, date(start_year, 9, 15)),
        (3, date(start_year, 12, 15)),
        (4, date(start_year + 1, 3, 15)),
    ]


@dataclass(frozen=True)
class InstallmentPayment:
    """One instalment's recorded payment. `paid_date=None` means not yet
    paid — it will not count toward any instalment's cumulative total."""
    installment_number: int
    paid_amount_paise: int
    paid_date: Optional[date] = None


@dataclass(frozen=True)
class InstallmentInterestResult:
    installment_number: int
    due_date: date
    cumulative_required_percent: int
    trigger_percent: int
    required_cumulative_paise: int
    actual_cumulative_paid_paise: int  # only payments with paid_date <= this due date count
    is_short: bool                     # whether the trigger tolerance was breached
    shortfall_paise: int
    interest_months: int
    interest_paise: int


@dataclass(frozen=True)
class AdvanceTaxInterestResult:
    installments: tuple[InstallmentInterestResult, ...]
    total_interest_paise: int


def compute_234c_interest(
    fy: str,
    estimated_tax_paise: int,
    payments: list[InstallmentPayment],
) -> AdvanceTaxInterestResult:
    """Section 234C interest for deferment of advance tax.

    A payment's `paid_date` counts toward an instalment's cumulative total
    only if it is on or before THAT instalment's own due date — a lump
    payment recorded late against instalment N's slot still correctly
    counts toward instalment N+1 (and later)'s cumulative-by-due-date
    total, since by then it has genuinely been paid.
    """
    if estimated_tax_paise <= 0:
        return AdvanceTaxInterestResult(installments=tuple(), total_interest_paise=0)

    due_dates = dict(installment_schedule(fy))
    results = []
    total = 0
    for rule in INSTALLMENT_RULES:
        due_date = due_dates[rule.number]
        actual_cumulative = sum(
            p.paid_amount_paise for p in payments
            if p.paid_date is not None and p.paid_date <= due_date
        )
        required_cumulative = _round_paise(estimated_tax_paise * rule.cumulative_required_percent, 100)
        trigger_amount = _round_paise(estimated_tax_paise * rule.trigger_percent, 100)
        is_short = actual_cumulative < trigger_amount
        shortfall = max(0, required_cumulative - actual_cumulative) if is_short else 0
        interest = _round_paise(shortfall * _INTEREST_RATE_PERCENT_PER_MONTH * rule.interest_months, 100)
        results.append(InstallmentInterestResult(
            installment_number=rule.number,
            due_date=due_date,
            cumulative_required_percent=rule.cumulative_required_percent,
            trigger_percent=rule.trigger_percent,
            required_cumulative_paise=required_cumulative,
            actual_cumulative_paid_paise=actual_cumulative,
            is_short=is_short,
            shortfall_paise=shortfall,
            interest_months=rule.interest_months,
            interest_paise=interest,
        ))
        total += interest

    return AdvanceTaxInterestResult(installments=tuple(results), total_interest_paise=total)
