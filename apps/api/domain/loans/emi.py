"""The equated monthly instalment a loan calculator shows (POST-A-266, part 2).

THE CALCULATOR IS A GUIDE AND THE LOAN AGREEMENT IS THE DOCUMENT OF RECORD. The loans screen used to work this out in
the browser with a binary floating-point power, which is arithmetic the rule "no business logic in the frontend" puts
here. It is the standard reducing-balance annuity:

    EMI = P x r x (1 + r)^n / ((1 + r)^n - 1),   r = annual rate / 12

worked in exact decimal arithmetic (the power is an integer power, so nothing is approximated before the last step)
and rounded half up to the paisa once, at the end. It embeds no statutory figure: the rate, the principal and the
tenure are what the person typed. What it does NOT know is how a particular lender rounds its instalment, whether it
charges interest from the disbursement date for a broken first period, or whether the rate is fixed; that is why the
screen says the agreement's figure is the one to record, and why nothing stores this number.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, localcontext

# A rate in basis points of a year: 10.5% is 1050.
_BPS_PER_UNIT = Decimal(10_000)
_MONTHS_PER_YEAR = Decimal(12)


def emi_paise(principal_paise: int, annual_rate_bps: int, months: int) -> int:
    """The monthly instalment in whole paise.

    A zero rate is the principal spread evenly, which is the formula's own limit as the rate falls to nothing.
    Refuses a principal or a tenure that is not positive and a negative rate, with ValueError.
    """
    if isinstance(principal_paise, bool) or isinstance(annual_rate_bps, bool) or isinstance(months, bool):
        raise ValueError("principal, rate and tenure are whole numbers")
    if principal_paise <= 0:
        raise ValueError("The principal must be more than nil.")
    if months <= 0:
        raise ValueError("The tenure must be at least one month.")
    if annual_rate_bps < 0:
        raise ValueError("The interest rate cannot be negative.")
    with localcontext() as ctx:
        ctx.prec = 80
        p = Decimal(principal_paise)
        if annual_rate_bps == 0:
            emi = p / Decimal(months)
        else:
            r = Decimal(annual_rate_bps) / _BPS_PER_UNIT / _MONTHS_PER_YEAR
            growth = (Decimal(1) + r) ** months
            emi = p * r * growth / (growth - Decimal(1))
        return int(emi.quantize(Decimal(1), rounding=ROUND_HALF_UP))
