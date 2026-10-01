"""How long the practice's own fee invoices take to be paid, from the receipts.

WHY THIS EXISTS (ai-08)
    The Executive Dashboard showed "Avg Collection Days: 0" for every firm. It
    was a literal in `get_executive_dashboard`, beside a literal 0 for
    outstanding invoices and outstanding amount — three KPIs on a screen sold as
    intelligence that nothing computed. A CA reads "0 days" as "everybody pays
    on the day", which is the opposite of an unknown.

THE RULE
    Days to collect is measured on what was actually SETTLED, weighted by how
    much: for every allocation of a receipt to an invoice,

        days   = receipt date - invoice date          (never below 0)
        weight = the paise that allocation settled

    and the figure is  sum(weight x days) / sum(weight),  rounded half up to a
    whole day. Weighting by paise rather than averaging per invoice is what
    stops a Rs 500 invoice paid in a day from cancelling a Rs 5,00,000 one paid
    in ninety, which is the case a partner is asking about.

    ⚠️ An allocation is the right unit, not an invoice. An invoice paid in two
    instalments was collected over two different periods, and one number for it
    would either lose the first instalment or date the second one early.

    A receipt dated BEFORE the invoice it settles (an advance) counts as 0 days,
    not a negative one: the invoice was collected the moment it existed, and a
    negative day would let advances drag the average below what any single
    invoice took.

WHAT IT REFUSES
    * No settled allocation in the window -> `None`, never 0. "Nothing was
      collected in this window" and "everything was collected on the day" are
      different facts and a 0 asserts the second.
    * An allocation whose receipt date or invoice date cannot be read is LEFT
      OUT and counted in `skipped`, so the answer says how many it could not
      use rather than quietly averaging the rest.
    * A voided allocation (a reversed receipt) is not a collection and is
      excluded by the caller's `is_voided` flag — it is not in the sum and not
      in `skipped`, because it is not a defect in the data.

WHAT IT DOES NOT DO
    It is not DSO. Days-sales-outstanding divides the receivable balance by
    credit sales over a period; this measures the time payment actually took.
    The two answer different questions and the dashboard names this one for what
    it is.

Pure: no database handle. `services/collections_service.average_days_to_collect`
fetches the rows.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Iterable, Optional


@dataclass(frozen=True)
class CollectionDays:
    """The answer and what it was computed from."""
    days: Optional[int]          # None = nothing settled in the window
    settled_paise: int           # sum of the weights
    allocations: int             # how many allocations were averaged
    skipped: int                 # unreadable dates, left out

    def as_dict(self) -> dict:
        return {
            "days": self.days,
            "settled_paise": self.settled_paise,
            "allocations": self.allocations,
            "skipped": self.skipped,
        }


def _day(value) -> Optional[date]:
    """An ISO date or datetime string (or a date) as a date; None if unreadable."""
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def average_days_to_collect(allocations: Iterable[dict]) -> CollectionDays:
    """Each row: {allocated_paise, receipt_date, invoice_date, is_voided?}.

    Integer arithmetic throughout (CLAUDE.md: every rupee calculation is integer
    paise). Rounding is half up on a non-negative quotient.
    """
    weight_total = 0
    weighted_days = 0
    used = 0
    skipped = 0
    for row in allocations:
        if row.get("is_voided"):
            continue
        paise = row.get("allocated_paise")
        try:
            paise = int(paise)
        except (TypeError, ValueError):
            skipped += 1
            continue
        if paise <= 0:
            # A nil allocation settled nothing; it is neither a collection nor
            # a defect, and a zero weight would not move the average anyway.
            continue
        received = _day(row.get("receipt_date"))
        invoiced = _day(row.get("invoice_date"))
        if received is None or invoiced is None:
            skipped += 1
            continue
        days = max(0, (received - invoiced).days)
        weight_total += paise
        weighted_days += paise * days
        used += 1

    if weight_total == 0:
        return CollectionDays(None, 0, used, skipped)
    # Half up: (2n + d) // 2d is round(n / d) for n, d >= 0.
    days = (2 * weighted_days + weight_total) // (2 * weight_total)
    return CollectionDays(days, weight_total, used, skipped)
