"""
Rule 37 — input tax credit reversed when the supplier goes unpaid for 180 days.

THE RULE
    CGST Act §16(2), second proviso: a registered person who has taken input tax
    credit on an inward supply must pay the supplier the value of the supply
    together with the tax within 180 days of the invoice date.

    Rule 37(1) of the CGST Rules: failing that, the credit is reversed to the
    extent NOT PAID — proportionate, not all-or-nothing. The reversal is made in
    the return for the tax period immediately following the one in which the 180
    days expire, with interest under §50.

    Rule 37(4): when the supplier is eventually paid, the credit is re-availed.
    The §16(4) time limit does not bite on that re-availment — a re-availed
    credit is not a fresh claim.

WHY THIS IS ITS OWN MODULE
    It is arithmetic on dates and integer paise with statutory consequences, and
    CLAUDE.md wants every financial calculation unit-tested. Nothing here reads
    a database or knows what a Supabase row looks like, so the tests are about
    the rule rather than about plumbing.

WHAT COUNTS AS PAID — AND THE ASSUMPTION IN IT
    TDS deducted at source under the Income Tax Act is treated here as
    discharged. It is not money withheld from the supplier: it is remitted to
    the government on the supplier's behalf and credited to them, so the value
    of the supply has been settled even though less cash moved.

    This is the ordinary reading and the ordinary practice, but it IS an
    interpretation, and it changes the number a CA files. It is applied in one
    named function so it can be found, argued with and changed in one place —
    and it is worth confirming with the CA rather than taking from this comment.
"""
from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

# CGST Act §16(2), second proviso.
RULE37_DAYS = 180


def payment_due_by(bill_date: date) -> date:
    """The last day the supplier can be paid before the credit must be reversed.

    Day 180 counted from the invoice date, so a bill dated 1 January is due by
    30 June and becomes overdue on 1 July.
    """
    return bill_date + timedelta(days=RULE37_DAYS)


def days_outstanding(bill_date: date, as_of: date) -> int:
    """Days elapsed since the invoice date. Negative for a future-dated bill."""
    return (as_of - bill_date).days


def is_overdue(bill_date: date, as_of: date) -> bool:
    """True once 180 days have passed without full payment being the caller's
    concern — this is the date test alone."""
    return as_of > payment_due_by(bill_date)


def discharged_paise(paid_paise: int, tds_paise: int = 0) -> int:
    """What has been settled against the bill.

    See the module docstring on TDS: deducted tax is remitted to the government
    on the supplier's behalf, so the supplier is credited with it. Treating it
    as unpaid would reverse credit on a bill that is, in substance, settled.
    """
    return max(0, int(paid_paise) + int(tds_paise))


def unpaid_paise(total_paise: int, paid_paise: int, tds_paise: int = 0) -> int:
    """The part of the bill still owed to the supplier. Never negative — an
    overpayment is not a negative liability for this purpose."""
    return max(0, int(total_paise) - discharged_paise(paid_paise, tds_paise))


def _proportionate(itc_paise: int, unpaid: int, total_paise: int) -> int:
    """itc x unpaid / total, in integer paise, rounded UP.

    Rule 37(1) reverses credit "proportionate to the amount not paid", so a
    part-paid bill reverses part of the credit.

    ROUNDING IS A CHOICE AND THIS ONE IS DELIBERATE. The exact figure is rarely
    a whole number of paise, and the two directions are not symmetrical:

      * reversing a paisa too little leaves a shortfall of credit that should
        have been reversed, which carries interest under §50 until it is
        corrected;
      * reversing a paisa too much is re-availed under Rule 37(4) the moment the
        supplier is paid.

    So it rounds up. Ceiling division is written as -(-a // b) rather than with
    math.ceil to keep it in integers — a float divide here would be exactly the
    arithmetic CLAUDE.md forbids for money.
    """
    if total_paise <= 0 or unpaid <= 0 or itc_paise <= 0:
        return 0
    if unpaid >= total_paise:
        return int(itc_paise)
    return -(-int(itc_paise) * int(unpaid) // int(total_paise))


def reversal_for_bill(
    *, total_paise: int, paid_paise: int, tds_paise: int = 0,
    cgst_paise: int = 0, sgst_paise: int = 0, igst_paise: int = 0,
) -> dict:
    """How much credit falls to be reversed on this bill, head by head.

    Each tax head is reversed proportionately in its own right rather than
    apportioning one combined figure, because GSTR-3B table 4(B) reports IGST,
    CGST and SGST separately and they have to add up per head.
    """
    unpaid = unpaid_paise(total_paise, paid_paise, tds_paise)
    cgst = _proportionate(cgst_paise, unpaid, total_paise)
    sgst = _proportionate(sgst_paise, unpaid, total_paise)
    igst = _proportionate(igst_paise, unpaid, total_paise)
    return {
        "unpaid_paise": unpaid,
        "cgst_paise": cgst,
        "sgst_paise": sgst,
        "igst_paise": igst,
        "total_paise": cgst + sgst + igst,
    }


def reversal_period(bill_date: date) -> str:
    """The GSTR-3B period the reversal belongs in, as 'MMYYYY'.

    Rule 37(1): the return for the tax period IMMEDIATELY FOLLOWING the period
    in which the 180 days expire — not the period the bill was raised in, and
    not the period the 180 days ran out in. Reporting it against the wrong month
    is the most common way this gets filed incorrectly.
    """
    expiry = payment_due_by(bill_date)
    month = expiry.month + 1
    year = expiry.year + (1 if month > 12 else 0)
    if month > 12:
        month = 1
    return f"{month:02d}{year:04d}"


def parse_iso(value: Optional[str]) -> Optional[date]:
    """'YYYY-MM-DD' → date, or None. Rows arrive as strings from PostgREST."""
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
