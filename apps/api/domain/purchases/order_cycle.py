"""The purchase cycle BEFORE the bill, and the two statutes that make it one.

WHY THIS EXISTS (PUR-25)
    The purchase cycle started at the bill. A practice's clients raise a
    purchase order, receive the goods against it and only then book the
    supplier's invoice — and neither of the first two documents existed, so
    there was nothing to check the bill against and no record of WHEN the
    goods actually arrived.

    That second absence is not a control problem, it is a statutory one, and
    in two places:

      * CGST s.16(2)(b) allows the input tax credit only where the recipient
        "has received the goods or services". The bill is the document; the
        RECEIPT is a separate condition, and nothing in the books recorded it.
      * MSMED s.15 requires payment within the time agreed in writing or, in
        its absence, before the appointed day — which s.2(b) fixes at fifteen
        days from the day of ACCEPTANCE. The Explanation to s.2(b) makes the
        day of acceptance the day of actual DELIVERY, unless the buyer objects
        in writing within fifteen days. `domain/income_tax/section_43b_h.py`
        has had to use the bill date as a proxy and says so in a caveat on
        every answer; a goods receipt is the real date.

WHAT THIS MODULE IS AND IS NOT
    It is the commercial chain — the statuses, what a conversion carries, and
    what a purchase order still has open. The MATCH is
    `domain/purchases/three_way_match.py` and the s.16(2)(b) and s.15
    consequences are stated there, beside the comparison that produces them.

    Neither module posts anything. A purchase order commits the client to buy
    and a goods receipt records an arrival; the EXPENSE, the input credit and
    the payable all arise when the bill is received, which is the existing
    path and is untouched.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

#: Where a purchase order is in its life. Closed and cancelled are DECISIONS a
#: CA takes — the supplier short-shipped and will not send the rest — so
#: nothing recomputes them.
ORDER_STATUSES = ("draft", "approved", "partially_received", "received",
                  "closed", "cancelled")
ORDER_OPEN_STATUSES = ("approved", "partially_received")

#: A goods receipt is either recorded or cancelled. There is no "posted": it
#: posts nothing.
GRN_STATUSES = ("draft", "recorded", "cancelled")

#: The sentence every purchase order and goods receipt carries.
POSTS_NOTHING = (
    "A purchase order commits the client to buy and a goods receipt records "
    "that the goods arrived. Neither posts a journal: the expense, the input "
    "tax credit and the payable all arise when the supplier's bill is "
    "received."
)


def series_kind_of(kind: str) -> str:
    """The numbering series a document of this kind draws from.

    Neither document is issued to anybody outside the client's own business,
    so CGST Rule 46(b) does not reach either — but the product imposes its own
    uniqueness per client per kind, because two purchase orders sharing a
    number is how a supplier delivers against the wrong one.
    """
    k = (kind or "").strip().lower()
    if k in ("purchase_order", "goods_receipt"):
        return k
    raise ValueError(f"Unknown pre-bill document kind {kind!r}.")


def to_decimal(value) -> Decimal:
    """A stored quantity, whatever shape PostgREST handed it back in.

    `Decimal(str(v))`, never `Decimal(v)` on a float — NUMERIC(10,3) does not
    survive a float round trip, which is the same rule the money boundary
    keeps.
    """
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _q(value: Decimal) -> str:
    return str(Decimal(value).quantize(Decimal("0.001")))


@dataclass(frozen=True)
class OpenLine:
    """One purchase-order line and what is left of it."""
    order_line_id: str
    description: str
    ordered_qty: Decimal
    received_qty: Decimal
    billed_qty: Decimal

    @property
    def unreceived_qty(self) -> Decimal:
        return max(Decimal(0), self.ordered_qty - self.received_qty)

    @property
    def unbilled_qty(self) -> Decimal:
        return max(Decimal(0), self.ordered_qty - self.billed_qty)

    def as_dict(self) -> dict:
        return {
            "order_line_id": self.order_line_id,
            "description": self.description,
            "ordered_qty": _q(self.ordered_qty),
            "received_qty": _q(self.received_qty),
            "billed_qty": _q(self.billed_qty),
            "unreceived_qty": _q(self.unreceived_qty),
            "unbilled_qty": _q(self.unbilled_qty),
        }


def open_quantities(order_lines: Iterable[dict],
                    received_by_line: Optional[dict] = None,
                    billed_by_line: Optional[dict] = None) -> list:
    """Per order line: ordered, received, billed, and what is left of each.

    RECEIVED AND BILLED ARE TWO DIFFERENT CLOCKS, and a purchase order needs
    both. Goods arrive on a challan and the invoice follows a month later
    (which is Rule 55's whole premise on the other side of the transaction),
    and a service is often billed before it is performed. An order tracking
    one figure would show a fully received order as open, or a fully billed
    one as never delivered — and the second matters, because s.16(2)(b)
    conditions the credit on RECEIPT and not on the bill.
    """
    received = received_by_line or {}
    billed = billed_by_line or {}
    out: list = []
    for ln in order_lines or []:
        lid = str(ln.get("id") or "")
        out.append(OpenLine(
            order_line_id=lid,
            description=str(ln.get("description") or ""),
            ordered_qty=to_decimal(ln.get("quantity")),
            received_qty=to_decimal(received.get(lid)),
            billed_qty=to_decimal(billed.get(lid)),
        ))
    return out


def order_status_for(lines: Iterable, current: str) -> str:
    """What an open order's status becomes once these receipts are in.

    Applied ONLY to an order that is currently live. `closed` and `cancelled`
    are decisions somebody took — the supplier short-shipped and will not send
    the rest — and recomputing would reopen them on every read.
    """
    if current not in ORDER_OPEN_STATUSES:
        return current
    rows = list(lines)
    if not rows:
        return current
    if all(ln.unreceived_qty == 0 for ln in rows):
        return "received"
    if any(ln.received_qty > 0 for ln in rows):
        return "partially_received"
    return "approved"


def over_receipt(line: OpenLine, quantity: Decimal) -> Optional[str]:
    """Receiving more than was ordered is refused, never clamped.

    Clamping would take the ordered quantity into stock and lose the excess
    with no record of goods that are physically on the premises; allowing it
    would make the order's own figures stop describing what was agreed. A
    supplier who sent more than was ordered is an amended order or a return,
    and both are decisions.
    """
    if quantity <= 0:
        return f"{line.description}: a receipt must be of a positive quantity."
    if quantity > line.unreceived_qty:
        return (f"{line.description}: {_q(quantity)} is more than the "
                f"{_q(line.unreceived_qty)} still outstanding on this order "
                f"line ({_q(line.ordered_qty)} ordered, "
                f"{_q(line.received_qty)} already received). Amend the order "
                f"if more was agreed, or record a return.")
    return None


#: The line fields a conversion carries forward. A list rather than "everything
#: on the row": an order line carries its own id, its own parent and its own
#: timestamps, and copying those would either collide or silently re-parent.
LINE_FIELDS_CARRIED = (
    "description", "hsn_sac", "quantity", "unit", "rate_paise",
    "gst_rate_percent", "is_service", "service_catalogue_id",
    "expense_account_id", "itc_eligible", "blocked_credit_reason",
    "tds_applicable", "cess_rate_bps", "cess_specific_paise_per_unit",
)

#: Header fields carried. The DATE is not among them: an order raised in March
#: and billed in April is an April bill, and carrying the order's date forward
#: would date it into a financial year that may already be closed.
HEADER_FIELDS_CARRIED = (
    "vendor_id", "vendor_name", "vendor_gstin", "place_of_supply",
    "is_inter_state", "currency", "notes",
)


def carry_line(line: dict) -> dict:
    """One line, ready to be a line of the next document in the chain.

    `itc_eligible` and `expense_account_id` travel because they are decisions
    the CA made once, on the order — the same reasoning
    `recurring_purchase_bill_service` records for a template. Defaulting them
    at conversion would re-decide s.17(5) every time an order is billed.
    """
    return {f: line.get(f) for f in LINE_FIELDS_CARRIED if line.get(f) is not None}


def carry_header(header: dict) -> dict:
    return {f: header.get(f) for f in HEADER_FIELDS_CARRIED
            if header.get(f) is not None}
