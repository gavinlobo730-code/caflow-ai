"""Purchase order against goods receipt against bill — and what the law makes
of the answer.

WHY A THREE-WAY MATCH IS NOT MERELY A CONTROL HERE (PUR-25)
    The familiar reason to compare the three is that it stops a bill being
    paid for goods nobody received or at a price nobody agreed. Both are real.
    But in an Indian practice the comparison also settles two statutory
    questions that nothing else in the books can answer:

    1. CGST s.16(2)(b) — RECEIPT IS A CONDITION OF THE CREDIT.
       The input tax credit is available only where the recipient "has
       received the goods or services", and the bill is not evidence of that:
       a supplier can invoice in March for goods that arrive in April, and the
       credit belongs to April. Nothing in this product recorded receipt at
       all, so the condition could not be tested. A goods receipt is that
       record.

    2. MSMED s.15 RUNS FROM ACCEPTANCE, AND ACCEPTANCE IS DELIVERY.
       s.2(b) fixes the appointed day at fifteen days from the day of
       acceptance or deemed acceptance, and its Explanation makes the day of
       acceptance the day of ACTUAL DELIVERY — unless the buyer objects in
       writing within fifteen days of delivery, when it is the day the
       objection is removed. `domain/income_tax/section_43b_h.py` has had to
       use the BILL date as a proxy and carries a caveat saying so on every
       answer. A goods receipt supplies the real date, and its `objection`
       fields carry the Explanation's second limb.

WHAT THIS MODULE REFUSES TO DO
    * IT REPORTS; IT NEVER BLOCKS A BILL. A supplier who short-ships or
      over-charges has still sent a bill, and the CA still has to book what
      arrived — refusing would push the entry outside the system, which is the
      one outcome worse than a mismatch nobody looked at. The one thing that
      IS refused is an over-RECEIPT against the order, because goods on the
      premises in excess of what was ordered mean the order is wrong.
    * NO TOLERANCE IS APPLIED, AND NONE IS INVENTED. "Within 2%" is a firm's
      own procurement policy, not a rule, and a tolerance written in here
      would silently pass a discrepancy somebody has to see. Every difference
      is stated exactly, and `NO_TOLERANCE_IS_APPLIED` says so on every
      answer.
    * NO PRICE VARIANCE IS POSTED. A full ERP books the difference between the
      ordered and the invoiced price to a variance account; this product costs
      a receipt at the BILL's own taxable value plus its blocked tax
      (INV-05a), so the bill IS the cost and there is no variance to post. A
      variance account here would double-count.
    * A BILL WITH NO ORDER IS NOT A FINDING. Most purchases a practice sees —
      professional fees, rent, utilities — are never ordered, and reporting
      each as unmatched would bury the ones that matter.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional

from domain.purchases.order_cycle import to_decimal
from domain.money_text import rupees_paise

NO_TOLERANCE_IS_APPLIED = (
    "Every difference below is stated exactly. No tolerance is applied: "
    "'within 2%' is a firm's own procurement policy rather than a rule, and a "
    "tolerance written into the engine would silently pass a discrepancy "
    "somebody has to look at."
)

SECTION_16_2_B = (
    "CGST Act s.16(2)(b): the input tax credit is available only where the "
    "recipient has RECEIVED the goods or services. A supplier's invoice is "
    "not evidence of that — an invoice dated March for goods that arrive in "
    "April carries credit that belongs to April."
)

#: The first proviso to s.16(2) — "bill to ship to". Named rather than
#: modelled: whether goods delivered to a third party on the client's
#: direction are deemed received by the client is a fact about the
#: arrangement, and no column holds it.
BILL_TO_SHIP_TO_NOT_MODELLED = (
    "The first proviso to CGST s.16(2) deems the recipient to have received "
    "goods delivered to a third party on their direction ('bill to ship to'). "
    "Whether an arrangement is one is a fact about the contract that no column "
    "here holds, so a bill with no goods receipt is REPORTED rather than "
    "treated as an unmet condition."
)

MSMED_ACCEPTANCE = (
    "MSMED Act s.15 with s.2(b): payment is due before the appointed day, "
    "which is fifteen days from the day of ACCEPTANCE, and the Explanation to "
    "s.2(b) makes the day of acceptance the day of ACTUAL DELIVERY unless the "
    "buyer objects in writing within fifteen days of delivery — when it is the "
    "day the objection is removed."
)


# ── One line, across the three documents ─────────────────────────────────────

@dataclass(frozen=True)
class MatchLine:
    """A bill line, with whatever the order and the receipts say about it."""
    bill_line_id: str
    description: str
    billed_qty: Decimal
    billed_rate_paise: int
    #: None where the bill line names no order line — which is ordinary.
    order_line_id: Optional[str] = None
    ordered_qty: Optional[Decimal] = None
    ordered_rate_paise: Optional[int] = None
    #: Summed over the goods receipts that named this order line.
    received_qty: Optional[Decimal] = None

    @property
    def quantity_difference(self) -> Optional[Decimal]:
        """Billed less received. Positive means billed for more than arrived."""
        if self.received_qty is None:
            return None
        return self.billed_qty - self.received_qty

    @property
    def rate_difference_paise(self) -> Optional[int]:
        """Billed less ordered, per unit. Positive means over-charged."""
        if self.ordered_rate_paise is None:
            return None
        return int(self.billed_rate_paise) - int(self.ordered_rate_paise)

    def as_dict(self) -> dict:
        return {
            "bill_line_id": self.bill_line_id,
            "description": self.description,
            "billed_qty": _q(self.billed_qty),
            "billed_rate_paise": int(self.billed_rate_paise),
            "order_line_id": self.order_line_id,
            "ordered_qty": _q(self.ordered_qty) if self.ordered_qty is not None else None,
            "ordered_rate_paise": self.ordered_rate_paise,
            "received_qty": _q(self.received_qty) if self.received_qty is not None else None,
            "quantity_difference": (_q(self.quantity_difference)
                                    if self.quantity_difference is not None else None),
            "rate_difference_paise": self.rate_difference_paise,
        }


def _q(value) -> str:
    return str(Decimal(value).quantize(Decimal("0.001")))


@dataclass
class MatchResult:
    bill_id: str
    matched: bool = False
    #: True where the bill names an order at all.
    has_order: bool = False
    #: True where any goods receipt exists against this bill's order.
    has_receipt: bool = False
    lines: list = field(default_factory=list)
    #: One sentence per real difference, in the CA's own terms.
    differences: list = field(default_factory=list)
    #: Things nobody can answer from the documents held.
    gaps: list = field(default_factory=list)
    caveats: list = field(default_factory=list)
    #: The acceptance date MSMED s.15 runs from, where a receipt supplies one.
    acceptance_date: Optional[str] = None
    acceptance_source: str = ""

    def as_dict(self) -> dict:
        return {
            "bill_id": self.bill_id,
            "matched": self.matched,
            "has_order": self.has_order,
            "has_receipt": self.has_receipt,
            "lines": [ln.as_dict() for ln in self.lines],
            "differences": list(self.differences),
            "gaps": list(self.gaps),
            "caveats": list(self.caveats),
            "acceptance_date": self.acceptance_date,
            "acceptance_source": self.acceptance_source,
            # CA REVIEW REQUIRED — this reports. It blocks nothing and posts
            # nothing.
            "ca_review_required": True,
        }


def match(*, bill_id: str, bill_lines: list, order_lines: Optional[list] = None,
          received_by_order_line: Optional[dict] = None,
          receipt_dates: Optional[list] = None,
          objection_removed_on: Optional[str] = None) -> MatchResult:
    """Compare one bill against its order and its goods receipts.

    `bill_lines` carry `order_line_id` where the CA linked them; a line that
    does not is compared against nothing and says so, because most purchases
    a practice sees are never ordered.
    """
    out = MatchResult(bill_id=bill_id)
    out.caveats = [NO_TOLERANCE_IS_APPLIED, SECTION_16_2_B, MSMED_ACCEPTANCE]

    by_order_line = {str(ln.get("id")): ln for ln in (order_lines or [])}
    received = received_by_order_line or {}
    out.has_order = bool(by_order_line)
    out.has_receipt = bool(received)

    for raw in bill_lines or []:
        oid = str(raw.get("order_line_id") or "") or None
        order = by_order_line.get(oid) if oid else None
        line = MatchLine(
            bill_line_id=str(raw.get("id") or ""),
            description=str(raw.get("description") or ""),
            billed_qty=to_decimal(raw.get("quantity")),
            billed_rate_paise=int(raw.get("rate_paise") or 0),
            order_line_id=oid,
            ordered_qty=to_decimal(order.get("quantity")) if order else None,
            ordered_rate_paise=(int(order.get("rate_paise") or 0)
                                if order else None),
            received_qty=(to_decimal(received.get(oid))
                          if oid and oid in received else None),
        )
        out.lines.append(line)

        if oid and order is None:
            out.gaps.append(
                f"{line.description}: the bill line names an order line that "
                f"is not on this order.")
            continue
        if order is None:
            continue

        qd = line.quantity_difference
        if qd is None:
            out.gaps.append(
                f"{line.description}: no goods receipt names this order line, "
                f"so what arrived is not recorded and CGST s.16(2)(b) cannot "
                f"be tested on it.")
        elif qd > 0:
            out.differences.append(
                f"{line.description}: billed for {_q(line.billed_qty)} but "
                f"{_q(line.received_qty)} was received — {_q(qd)} more than "
                f"arrived. The input tax credit on the excess is not available "
                f"until the goods are received (CGST s.16(2)(b)).")
        elif qd < 0:
            out.differences.append(
                f"{line.description}: {_q(line.received_qty)} was received and "
                f"the bill covers {_q(line.billed_qty)} — {_q(-qd)} received "
                f"and not yet billed.")

        rd = line.rate_difference_paise
        if rd:
            direction = "above" if rd > 0 else "below"
            out.differences.append(
                f"{line.description}: billed at "
                f"{_rupees(line.billed_rate_paise)} a unit, "
                f"{_rupees(abs(rd))} {direction} the "
                f"{_rupees(int(line.ordered_rate_paise or 0))} ordered.")

    if not out.has_order:
        out.gaps.append(
            "This bill is not linked to a purchase order, so there is nothing "
            "to match it against. Most purchases — fees, rent, utilities — are "
            "never ordered, so that is ordinary rather than a finding.")
    elif not out.has_receipt:
        out.gaps.append(BILL_TO_SHIP_TO_NOT_MODELLED)

    out.acceptance_date, out.acceptance_source = acceptance_date(
        receipt_dates or [], objection_removed_on)
    out.matched = out.has_order and out.has_receipt and not out.differences
    return out


def _rupees(paise: int) -> str:
    """A difference is read by a person, so it says rupees."""
    sign = "-" if paise < 0 else ""
    paise = abs(int(paise))
    return f"{sign}Rs {rupees_paise(paise)}"


# ── The MSMED s.15 clock ─────────────────────────────────────────────────────

def acceptance_date(receipt_dates: list,
                    objection_removed_on: Optional[str] = None) -> tuple:
    """The day MSMED s.15's fifteen days run from, and where it came from.

    THE EXPLANATION TO s.2(b) HAS TWO LIMBS AND THE SECOND DISPLACES THE
    FIRST. Acceptance is the day of actual DELIVERY; but where the buyer
    objects IN WRITING within fifteen days of delivery, it is the day the
    objection is removed — which is LATER, and therefore the direction that
    shortens nothing and cannot manufacture a disallowance.

    THE LAST RECEIPT, NOT THE FIRST. A part-shipped order is accepted when the
    goods the bill covers have all arrived; taking the earliest would start
    the clock before the supply was complete and report a disallowance on a
    bill paid in time.

    Returns `(None, reason)` where nothing supplies a date — never the bill
    date, because substituting one silently is what
    `domain/income_tax/section_43b_h.py` already does with a caveat, and doing
    it again here would hide that it happened.
    """
    if objection_removed_on:
        return str(objection_removed_on)[:10], (
            "MSMED s.2(b), Explanation, second limb — the buyer objected in "
            "writing and the clock runs from the day the objection was "
            "removed.")
    dates = sorted(str(d)[:10] for d in receipt_dates if d)
    if not dates:
        return None, (
            "No goods receipt is recorded against this bill, so the day of "
            "acceptance is not held. The s.43B(h) working falls back to the "
            "bill date and says so.")
    return dates[-1], (
        "MSMED s.2(b), Explanation — the day of actual delivery, taken as the "
        "LAST goods receipt against this bill's order, because a part-shipped "
        "order is accepted when the goods the bill covers have all arrived.")


def days_between(a: Optional[str], b: Optional[str]) -> Optional[int]:
    """Whole days from `a` to `b`, or None. Calendar days, never months —
    MSMED s.2(b) counts fifteen DAYS."""
    try:
        return (date.fromisoformat(str(b)[:10])
                - date.fromisoformat(str(a)[:10])).days
    except (TypeError, ValueError):
        return None
