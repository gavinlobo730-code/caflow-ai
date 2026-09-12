"""
What being late costs a deductor: IT Act §201(1A) interest and the §234E fee.

WHY THIS EXISTS (TDS-08)

    A client deducts ₹80,000 in June and deposits it on 20 August. The CA has
    to work out on paper that §201(1A)(ii) charges 1.5% per month or part from
    the DATE OF DEDUCTION — not from the due date — that June, July and August
    are three part-months, that the figure is ₹3,600, and that it goes on the
    challan under its own head. Nothing in this product computed it. §201(1A)
    appeared in a dozen comments and no function; §234E existed only inside
    the filing walk-through, which transmits nothing.

    Both are pure arithmetic over dates the register already holds, which is
    the whole reason it is worth doing: the deduction date is on the row, the
    deposit date is on the challan, and Rule 30(2)'s due date is already
    derived by `services/compliance_engine.tds_deposit_due_date`.

TWO LIMBS, TWO RATES, TWO CLOCKS — AND COLLAPSING THEM IS THE EASY ERROR

    §201(1A), in its own words:

        (i)  at one per cent for every month or part of a month on the amount
             of such tax from the date on which such tax was DEDUCTIBLE to the
             date on which such tax is DEDUCTED; and
        (ii) at one and one-half per cent for every month or part of a month
             on the amount of such tax from the date on which such tax was
             DEDUCTED to the date on which such tax is actually PAID.

    They are different failures. (i) is deducting late — the money was never
    withheld when the credit or payment fell due. (ii) is withholding on time
    and sitting on it. A deductor who did both owes both, over two different
    periods, at two different rates, and one function returning "the §201(1A)
    interest" would have to pick one and be wrong about the other. So there
    are two, named for their limbs.

    Note where limb (ii)'s clock STARTS. Not the Rule 30(2) due date — the
    date of deduction. Tax deducted on 25 June is due on 7 July; deposited on
    8 July it is one day late and carries interest for JUNE and JULY, two
    months, 3%. That single day costs 3% of the tax, and the surprise is the
    single most common §201(1A) complaint there is.

"MONTH OR PART OF A MONTH" IS NOT THE SAME ARITHMETIC AS IN §234A

    The phrase is identical and the counting is not, so this module has its
    own helper rather than reusing
    `domain/income_tax/advance_tax_interest_engine._months_or_part`.

    §234A charges "for every month or part of a month comprised in the PERIOD
    commencing on the date immediately following the due date" — a period, so
    the count is anniversary-to-anniversary: 15 June to 20 August is two whole
    months and five days, three part-months. That is what the advance-tax
    helper implements, and it is right there.

    §201(1A) is administered on CALENDAR months: the count is the number of
    calendar months the interval touches, both ends included. 30 June to
    1 July is two months on this reckoning and one on the other, and TRACES,
    Saral, Winman and ClearTDS all charge two. That is the reckoning a CA will
    be asked to pay against, so it is the one that belongs in a figure this
    product shows them.

    ⚠️ [S]-graded — stated from knowledge, not read. Direct egress is refused
    at this environment's proxy, so neither the section nor a TRACES worked
    example could be opened to confirm the convention, and the market-research
    pack carries nothing on it either. The error direction is deliberate: the
    calendar count is never SMALLER than the anniversary count, so a figure
    computed this way cannot tell a deductor they owe less interest than they
    do. Same reasoning as the ESI round-up — take the direction that is safe
    for whoever would otherwise carry the shortfall.

WHAT THIS MODULE REFUSES

    Tax that was never deducted at all. §201(1A)(i) runs "to the date on which
    such tax is deducted", and where there is no such date the first proviso
    to §201(1) runs the clock to the date the PAYEE furnished their return —
    a fact about somebody else's filing that this product does not hold and
    cannot infer. `interest_on_late_deduction` therefore needs a deduction
    date and says so; it does not substitute today's.

    Integer paise throughout. No float ever touches an amount.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional

#: §201(1A)(i) — failure to deduct. One per cent per month or part, in basis
#: points of the tax, so the arithmetic stays integral.
RATE_201_1A_I_BPS: int = 100
#: §201(1A)(ii) — deducted and not paid over. One and one-half per cent.
RATE_201_1A_II_BPS: int = 150

#: §234E — "a sum of two hundred rupees for every day during which the failure
#: continues", in integer paise.
FEE_234E_PER_DAY_PAISE: int = 200_00

LIMB_LATE_DEDUCTION = "201(1A)(i)"
LIMB_LATE_DEPOSIT = "201(1A)(ii)"


def months_or_part(from_date: date, to_date: date) -> int:
    """Calendar months touched by [from_date, to_date], both ends included.

    The §201(1A) reckoning — see the module docstring for why it differs from
    the §234A one and why the difference is not cosmetic. Nil where to_date is
    before from_date, so a clock that has not started cannot run backwards.
    A single day inside one calendar month is one month; a single day either
    side of a month boundary is two.
    """
    if to_date < from_date:
        return 0
    return (to_date.year - from_date.year) * 12 + (to_date.month - from_date.month) + 1


@dataclass(frozen=True)
class Interest:
    """One limb's answer. `applies` false means there was no default at all —
    which is a different statement from an interest of zero on a nil tax, and
    the two are distinguished so a screen can say "on time" rather than "₹0"."""
    limb: str
    applies: bool
    base_paise: int
    months: int
    rate_bps_per_month: int
    interest_paise: int
    from_date: Optional[date]
    to_date: Optional[date]
    reason: str

    def as_dict(self) -> dict:
        return {
            "limb": self.limb,
            "applies": self.applies,
            "base_paise": self.base_paise,
            "months": self.months,
            "rate_bps_per_month": self.rate_bps_per_month,
            "interest_paise": self.interest_paise,
            "from_date": self.from_date.isoformat() if self.from_date else None,
            "to_date": self.to_date.isoformat() if self.to_date else None,
            "reason": self.reason,
        }


def _charge(base_paise: int, bps: int, months: int) -> int:
    """base × rate × months, in integer paise. Floors — the residue is a
    fraction of a paisa, and the alternative is a float in a tax figure."""
    return max(0, int(base_paise)) * bps * months // 10_000


def interest_on_late_deposit(
    *,
    tax_paise: int,
    deducted_on: date,
    due_date: date,
    deposited_on: Optional[date],
    as_at: Optional[date] = None,
) -> Interest:
    """§201(1A)(ii) — tax deducted and paid over late, or not yet paid over.

    `due_date` decides WHETHER there is a default: §201(1A)(ii) bites on a
    failure "to pay the tax after so deducting", and tax in the government's
    hands by the Rule 30(2) date is not that. `deducted_on` decides HOW MUCH:
    once there is a default the clock runs from the deduction, which is why
    both dates are required and neither substitutes for the other.

    `deposited_on` None means still unpaid; the interest is then computed to
    `as_at` (default: the deposit date the caller would have used, so the
    caller must pass one) and keeps running. A caller that has neither a
    deposit date nor an as-at date gets a refusal rather than a figure.
    """
    end = deposited_on or as_at
    if end is None:
        return Interest(
            limb=LIMB_LATE_DEPOSIT, applies=False, base_paise=int(tax_paise),
            months=0, rate_bps_per_month=RATE_201_1A_II_BPS, interest_paise=0,
            from_date=deducted_on, to_date=None,
            reason=("This tax has not been deposited and no date was given to "
                    "compute the interest up to, so no §201(1A)(ii) figure is "
                    "stated. Interest is running from "
                    f"{deducted_on.isoformat()} at 1.5% for every month or "
                    "part of a month."),
        )
    if end <= due_date:
        return Interest(
            limb=LIMB_LATE_DEPOSIT, applies=False, base_paise=int(tax_paise),
            months=0, rate_bps_per_month=RATE_201_1A_II_BPS, interest_paise=0,
            from_date=deducted_on, to_date=end,
            reason=(f"Deposited on {end.isoformat()}, on or before the Rule "
                    f"30(2) due date of {due_date.isoformat()}. §201(1A)(ii) "
                    "charges interest on a failure to pay over, and there was "
                    "none."),
        )
    months = months_or_part(deducted_on, end)
    interest = _charge(tax_paise, RATE_201_1A_II_BPS, months)
    return Interest(
        limb=LIMB_LATE_DEPOSIT, applies=True, base_paise=int(tax_paise),
        months=months, rate_bps_per_month=RATE_201_1A_II_BPS,
        interest_paise=interest, from_date=deducted_on, to_date=end,
        reason=(f"Deducted {deducted_on.isoformat()}, due "
                f"{due_date.isoformat()}, paid over {end.isoformat()}. "
                f"§201(1A)(ii) charges 1.5% for every month or part of a "
                f"month from the date of DEDUCTION — {months} month(s) here, "
                "counted by calendar month."),
    )


def interest_on_late_deduction(
    *,
    tax_paise: int,
    deductible_on: date,
    deducted_on: Optional[date],
) -> Interest:
    """§201(1A)(i) — the tax was withheld later than it fell due to be withheld.

    `deductible_on` is the date of credit to the payee or of payment, whichever
    is earlier (§194C(3), §194J(1) and their neighbours all say so). Where the
    tax was never deducted at all this REFUSES rather than running the clock to
    today: the first proviso to §201(1) ends it at the date the PAYEE furnished
    their return, which is a fact about somebody else's filing.
    """
    if deducted_on is None:
        return Interest(
            limb=LIMB_LATE_DEDUCTION, applies=False, base_paise=int(tax_paise),
            months=0, rate_bps_per_month=RATE_201_1A_I_BPS, interest_paise=0,
            from_date=deductible_on, to_date=None,
            reason=("No tax was deducted, so §201(1A)(i) has no end date. The "
                    "first proviso to §201(1) runs the clock to the date the "
                    "PAYEE furnished their return of income — a fact about "
                    "the payee's own filing that this product does not hold. "
                    "The figure has to come from the payee's Form 26AS or "
                    "their acknowledgement."),
        )
    if deducted_on <= deductible_on:
        return Interest(
            limb=LIMB_LATE_DEDUCTION, applies=False, base_paise=int(tax_paise),
            months=0, rate_bps_per_month=RATE_201_1A_I_BPS, interest_paise=0,
            from_date=deductible_on, to_date=deducted_on,
            reason=(f"Deducted on {deducted_on.isoformat()}, on or before the "
                    f"date it fell due ({deductible_on.isoformat()}). "
                    "§201(1A)(i) charges interest on a failure to deduct, and "
                    "there was none."),
        )
    months = months_or_part(deductible_on, deducted_on)
    interest = _charge(tax_paise, RATE_201_1A_I_BPS, months)
    return Interest(
        limb=LIMB_LATE_DEDUCTION, applies=True, base_paise=int(tax_paise),
        months=months, rate_bps_per_month=RATE_201_1A_I_BPS,
        interest_paise=interest, from_date=deductible_on, to_date=deducted_on,
        reason=(f"Tax fell due to be deducted on {deductible_on.isoformat()} "
                f"and was deducted on {deducted_on.isoformat()}. §201(1A)(i) "
                f"charges 1% for every month or part of a month over that "
                f"period — {months} month(s), counted by calendar month."),
    )


@dataclass(frozen=True)
class LateFilingFee:
    """§234E. `capped` says the ₹200-a-day figure was cut down to the tax,
    which is the difference between a fee a CA can sanity-check and one they
    cannot."""
    applies: bool
    days_late: int
    uncapped_paise: int
    cap_paise: int
    fee_paise: int
    due_date: date
    filed_on: Optional[date]
    reason: str

    def as_dict(self) -> dict:
        return {
            "applies": self.applies,
            "days_late": self.days_late,
            "uncapped_paise": self.uncapped_paise,
            "cap_paise": self.cap_paise,
            "fee_paise": self.fee_paise,
            "capped": self.fee_paise < self.uncapped_paise,
            "due_date": self.due_date.isoformat(),
            "filed_on": self.filed_on.isoformat() if self.filed_on else None,
            "reason": self.reason,
        }


def fee_234e(
    *,
    due_date: date,
    filed_on: date,
    tax_deductible_paise: int,
) -> LateFilingFee:
    """§234E — ₹200 for every DAY the statement is late, capped at the tax.

    Days, not months: §234E is the one figure in this module counted in days,
    and mixing it up with §201(1A)'s months is how a fee ends up thirty times
    too small. The cap is "the amount of tax deductible or collectible" — the
    STATEMENT's total, not any one deductee's — and the fee must be paid
    before the statement can be delivered at all (§234E(4)), which is why it
    belongs beside the return rather than after it.

    §271H's ₹10,000–₹1,00,000 penalty for a late or incorrect statement is
    deliberately not computed: it is discretionary and not a function of any
    row.
    """
    cap = max(0, int(tax_deductible_paise))
    days_late = (filed_on - due_date).days
    if days_late <= 0:
        return LateFilingFee(
            applies=False, days_late=0, uncapped_paise=0, cap_paise=cap,
            fee_paise=0, due_date=due_date, filed_on=filed_on,
            reason=(f"Furnished on {filed_on.isoformat()}, on or before the "
                    f"Rule 31A due date of {due_date.isoformat()}. §234E "
                    "charges a fee for every day the failure continues, and "
                    "there was no failure."),
        )
    uncapped = days_late * FEE_234E_PER_DAY_PAISE
    fee = min(uncapped, cap)
    capped_note = (
        " That is more than the tax the statement reports, so §234E's own cap "
        "— the fee 'shall not exceed the amount of tax deductible or "
        "collectible' — brings it down to the tax."
        if fee < uncapped else "")
    return LateFilingFee(
        applies=True, days_late=days_late, uncapped_paise=uncapped,
        cap_paise=cap, fee_paise=fee, due_date=due_date, filed_on=filed_on,
        reason=(f"Due {due_date.isoformat()}, furnished {filed_on.isoformat()} "
                f"— {days_late} day(s) late. §234E charges ₹200 a day."
                + capped_note +
                " The fee is payable before the statement can be delivered "
                "(§234E(4))."),
    )
