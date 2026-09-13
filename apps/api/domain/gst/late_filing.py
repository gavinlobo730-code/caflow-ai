"""What being late with a GST return costs — §50 interest and the §47 late fee.

GST-21. For any late GSTR-3B the product prepares, Table 5.1 came out as zeros
(`gstr3b_computer` hardcoded `intr_ltfee`) and `services/filing_demo/gstr3b.py`
said plainly in its own text that "PracticeSync does not compute §50 interest
or §47 late fee". The CA worked both out by hand. ClearTax, IRIS and Tally all
show them before filing.

WHAT IS COMPUTED HERE AND WHAT IS REFUSED

The INTEREST is computed. Its rates are in the Act itself — §50(1) "at such
rate not exceeding eighteen per cent as may be notified" (notified at 18% by
Notification 13/2017-Central Tax) and §50(3) at twenty-four per cent — and the
rule that decides the BASE is textual rather than numeric.

The LATE FEE is REFUSED, and that is the deliberate half. §47(1) sets a
statutory ₹100 per day per Act capped at ₹5,000, but no registered person has
paid that since 2018: Notifications 4/2018 and 76/2018 reduced it, and 19/2021
and 20/2021 capped it by turnover band. Those figures are not held, because
this environment's egress proxy refuses every `.gov.in` and a late fee written
from memory is a number a CA would pay. So `late_fee` returns a NAMED GAP
saying exactly which notification to read, the same shape as the state
professional-tax slabs and the ESIC reason codes. A CA fills the table once;
until they do, nothing wrong is shown.

RULE 88B IS THE PART THAT IS EASY TO GET WRONG, AND IT IS THE EXPENSIVE ONE

Interest under §50(1) is NOT charged on the gross output tax. Rule 88B(1) — the
proviso inserted by the Finance Act 2021 and made retrospective to 01-07-2017
by the Finance Act 2022 — charges it only on "that portion of the tax which is
paid by debiting the electronic cash ledger", where the supplies are declared
in a return furnished AFTER the due date and before any §73/§74 proceeding
begins. A taxpayer with enough credit in the ledger to cover the whole
liability owes NO interest on it however late the return is. Charging on the
gross would routinely demand several times what is due.

Rule 88B(2) is the other case — tax NOT declared in that return, found later —
and there the charge is on the whole tax from the date it fell due.

§50(3) with Rule 88B(3) is narrower still: 24% on input tax credit "wrongly
availed AND UTILISED", from the date of utilisation. Credit availed and never
utilised carries nothing, and this module refuses to guess the utilised portion
rather than charging the availed one.

TWO CONVENTIONS, BOTH STATED RATHER THAN ASSUMED

  • DAYS, not months. §50 charges "for the period for which the tax remains
    unpaid", and the portal counts days: due 20 July, paid 21 July is one day.
    That is `(paid - due).days`, and it is NOT the §201(1A) "month or part of a
    month" arithmetic — see domain/tds/interest.py, where getting it in months
    would be thirty times wrong in the other direction.
  • ROUNDED UP to the paise. Interest is a sum the taxpayer OWES, so
    understating it leaves them short and a residual demand follows; the ESI
    contribution rounds up for the same reason (see CLAUDE.md), while the GST
    discount floors because there understating the DISCOUNT cannot
    under-declare tax. Each takes the direction that is safe for whoever
    carries the liability.

⚠️ TWO THINGS ARE `[S]`-GRADED AND BOTH FAIL GENEROUS

  • The divisor is 365 even in a leap year, which is what the portal's own
    formula uses; if a leap year should divide by 366 this OVER-states by
    0.27%, which is the safe direction.
  • The COVID concessional rates (Notification 31/2020 and its siblings, which
    gave nil and 9% for specified 2020 periods) are NOT held. A period covered
    by them is charged at 18% here — over-stated, and named in the result's
    caveats rather than silently applied.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Optional

from domain.reporting.amount_words import indian_rupees

# §50(1), notified at 18% per annum by Notification 13/2017-Central Tax.
SECTION_50_1_RATE_BPS = 1800
# §50(3) as substituted by the Finance Act 2022 — twenty-four per cent, on
# input tax credit wrongly availed AND utilised.
SECTION_50_3_RATE_BPS = 2400
# The portal's own divisor. See the leap-year caveat in the module docstring.
DAYS_IN_YEAR = 365

# The concessional-rate window nobody has transcribed. A return for a period
# inside it is charged at the full 18% and SAYS SO.
_COVID_RELIEF_FROM = date(2020, 2, 1)
_COVID_RELIEF_TO = date(2020, 8, 31)

GAP_LATE_FEE_RATES_NOT_HELD = "gst_late_fee_rates_not_held"


def _rupees(paise: int) -> str:
    return f"₹{indian_rupees(paise)}"


def _ceil_div(numerator: int, denominator: int) -> int:
    """Integer division rounding UP — see the module docstring on direction."""
    if denominator == 0:
        return 0
    return -(-numerator // denominator)


def days_late(due: date, paid: date) -> int:
    """Whole days of delay, never negative.

    `(paid - due).days`, which is what the portal counts: due 20 July and paid
    21 July is one day. Both are `date` objects, so there is no instant to be
    read back in the wrong zone — the trap the frontend's own day-count guard
    exists for.
    """
    return max(0, (paid - due).days)


@dataclass(frozen=True)
class InterestCharge:
    """One §50 charge, with the working a CA can check."""
    section: str
    base_paise: int
    rate_bps: int
    days: int
    interest_paise: int
    basis: str
    caveats: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "section": self.section,
            "base_paise": self.base_paise,
            "rate_bps": self.rate_bps,
            "days": self.days,
            "interest_paise": self.interest_paise,
            "basis": self.basis,
            "caveats": self.caveats,
        }


def _charge(*, section: str, base_paise: int, rate_bps: int, days: int,
            basis: str, caveats: list[str]) -> InterestCharge:
    base = max(0, int(base_paise or 0))
    interest = _ceil_div(base * rate_bps * days, 10_000 * DAYS_IN_YEAR)
    return InterestCharge(section=section, base_paise=base, rate_bps=rate_bps,
                          days=days, interest_paise=interest, basis=basis,
                          caveats=caveats)


def interest_on_late_return(
    *,
    due_date: date,
    filed_on: date,
    cash_payable_paise: int,
    period_start: Optional[date] = None,
) -> InterestCharge:
    """§50(1) with Rule 88B(1) — on the CASH portion only.

    `cash_payable_paise` is what `gstr3b_computer` already computes as the
    challan figure: output tax less the credit the ledger can lawfully spend on
    it, plus reverse-charge tax, which §2(82) excludes from "output tax" so
    §49(4) can never pay it from credit. Passing the GROSS output tax here
    would charge interest a taxpayer with sufficient credit does not owe at
    all, which is the whole point of the proviso.
    """
    days = days_late(due_date, filed_on)
    caveats: list[str] = []
    if period_start and _COVID_RELIEF_FROM <= period_start <= _COVID_RELIEF_TO:
        caveats.append(
            "This period falls in the window the 2020 concessional-rate "
            "notifications covered (Notification 31/2020 and its siblings gave "
            "nil and 9% for specified months). Those rates are NOT held here, "
            "so 18% has been applied — the figure is an over-statement. Check "
            "the notification for this class of taxpayer and this month."
        )
    return _charge(
        section="50(1)", base_paise=cash_payable_paise,
        rate_bps=SECTION_50_1_RATE_BPS, days=days, caveats=caveats,
        basis=(
            "Section 50(1) with Rule 88B(1): where the supplies are declared in "
            "a return furnished after the due date, interest runs only on the "
            "portion of tax paid by debiting the electronic CASH ledger — not "
            "on the gross output tax. 18% per annum, notified by Notification "
            "13/2017-Central Tax."
        ),
    )


def interest_on_undeclared_tax(
    *,
    due_date: date,
    paid_on: date,
    tax_paise: int,
) -> InterestCharge:
    """§50(1) with Rule 88B(2) — the OTHER case, and the base is the whole tax.

    Rule 88B(1)'s cash-only relief reaches tax DECLARED in a return furnished
    late. Tax that was never declared and comes out of a §73/§74 proceeding
    gets no such relief: interest runs on the total, from the date it fell due.
    A caller that used the cash figure here would understate the charge.
    """
    return _charge(
        section="50(1)", base_paise=tax_paise,
        rate_bps=SECTION_50_1_RATE_BPS, days=days_late(due_date, paid_on),
        caveats=[],
        basis=(
            "Section 50(1) with Rule 88B(2): tax not declared in the return for "
            "the period bears interest on the WHOLE amount from the date it "
            "was due, with none of the cash-ledger relief a late-but-declared "
            "liability gets. 18% per annum."
        ),
    )


def interest_on_wrongly_availed_credit(
    *,
    utilised_on: Optional[date],
    reversed_on: Optional[date],
    utilised_paise: Optional[int],
    availed_paise: int = 0,
) -> InterestCharge | dict:
    """§50(3) with Rule 88B(3) — 24%, on the credit UTILISED, never the availed.

    Returns a REFUSAL (a dict with `refused`) rather than a charge where the
    utilised portion or either date is not recorded. Credit wrongly availed and
    never utilised bears no interest at all — Rule 88B(3)'s explanation is
    about the balance in the electronic credit ledger falling below the wrongly
    availed amount — so substituting the availed figure would charge a taxpayer
    who owes nothing, at the higher of the two rates.
    """
    missing = []
    if utilised_paise is None:
        missing.append("how much of the credit was actually utilised")
    if utilised_on is None:
        missing.append("the date it was utilised")
    if reversed_on is None:
        missing.append("the date it was reversed or paid back")
    if missing:
        return {
            "refused": True,
            "section": "50(3)",
            "reason": (
                "Section 50(3) charges 24% on input tax credit wrongly availed "
                "AND UTILISED, from the date of utilisation to the date of "
                "reversal (Rule 88B(3)). Credit availed and never utilised "
                "bears no interest, so this is not computed from the availed "
                f"amount of {_rupees(availed_paise)}. Record " + ", ".join(missing) + "."
            ),
        }
    return _charge(
        section="50(3)", base_paise=int(utilised_paise or 0),
        rate_bps=SECTION_50_3_RATE_BPS,
        days=days_late(utilised_on, reversed_on), caveats=[],
        basis=(
            "Section 50(3) with Rule 88B(3): 24% per annum on input tax credit "
            "wrongly availed AND utilised, running from the date of "
            "utilisation to the date of reversal or payment."
        ),
    )


# ── The late fee, which is a gap ─────────────────────────────────────────────
#
# One entry per (return type, financial year), and the dict is EMPTY. Adding a
# row is a human step, like the state professional-tax slabs: read the
# notification in force for that year and that class of taxpayer, and write it
# down. Nothing here guesses.
@dataclass(frozen=True)
class LateFeeRate:
    """What one day of delay costs, and where the ceiling is.

    `per_day_paise` and `cap_paise` are the COMBINED figures (CGST + SGST), the
    way a portal shows them — §47 sets ₹100 a day capped at ₹5,000 under each
    Act, so the statutory combined figures are ₹200 and ₹10,000, and every
    notification since has reduced both halves together.
    """
    per_day_paise: int
    nil_return_per_day_paise: int
    cap_paise: int
    source: str


LATE_FEE_RATES: dict[tuple[str, str], LateFeeRate] = {}

# The statutory figures, recorded so nobody has to look them up to know what
# the notifications REDUCED. Deliberately NOT used as a fallback: charging
# ₹200 a day where ₹50 is notified is four times the fee, on a figure a CA
# would pay.
SECTION_47_1_STATUTORY_PER_DAY_PAISE = 200_00
SECTION_47_1_STATUTORY_CAP_PAISE = 10_000_00


@dataclass(frozen=True)
class LateFee:
    return_type: str
    financial_year: str
    days: int
    is_nil_return: bool
    fee_paise: int
    capped: bool
    source: str

    def as_dict(self) -> dict:
        return {
            "return_type": self.return_type,
            "financial_year": self.financial_year,
            "days": self.days,
            "is_nil_return": self.is_nil_return,
            "fee_paise": self.fee_paise,
            "capped": self.capped,
            "source": self.source,
        }


def late_fee(
    *,
    return_type: str,
    financial_year: str,
    due_date: date,
    filed_on: date,
    is_nil_return: bool = False,
) -> LateFee | dict:
    """§47 — a named GAP unless somebody has recorded the year's notification.

    The refusal is the point. §47(1) is ₹100 a day per Act capped at ₹5,000,
    and no registered person has paid that since 2018; the notified figures
    move by taxpayer turnover band and by return type, and this environment
    cannot reach a `.gov.in` to read them. A fee written from memory is a
    number a CA would pay over.
    """
    days = days_late(due_date, filed_on)
    key = (return_type.strip().lower(), financial_year.strip())
    rate = LATE_FEE_RATES.get(key)
    if rate is None:
        return {
            "refused": True,
            "code": GAP_LATE_FEE_RATES_NOT_HELD,
            "return_type": return_type,
            "financial_year": financial_year,
            "days": days,
            "reason": (
                f"This return is {days} day(s) late and the section 47 late fee "
                f"for {return_type.upper()} in FY {financial_year} is not "
                f"recorded. The statutory figure is ₹100 a day under each Act "
                f"capped at ₹5,000 (so ₹200 and ₹10,000 combined), but every "
                f"registered person has paid a REDUCED rate since Notifications "
                f"4/2018 and 76/2018, capped by turnover band since 19/2021 and "
                f"20/2021. Read the notification in force for this year and this "
                f"taxpayer's turnover and record it — the statutory figure is "
                f"not used as a fallback, because charging four times the "
                f"notified fee is a number somebody would pay."
            ),
        }
    per_day = rate.nil_return_per_day_paise if is_nil_return else rate.per_day_paise
    raw = per_day * days
    fee = min(raw, rate.cap_paise)
    return LateFee(return_type=return_type, financial_year=financial_year,
                   days=days, is_nil_return=is_nil_return, fee_paise=fee,
                   capped=fee < raw, source=rate.source)
