"""The sales cycle BEFORE the tax invoice, and what each step may and may not do.

WHY THIS EXISTS (SALES-21)
    The sales cycle started at the invoice. A practice's clients quote, take an
    order, deliver against it and only then bill — and none of the first three
    documents existed, so a CA either raised the tax invoice early (declaring a
    supply that has not happened) or kept the quotation in a spreadsheet and
    re-typed every line when it converted.

WHAT IS AND IS NOT A DOCUMENT UNDER THE ACT
    Three of the four are COMMERCIAL and carry no statutory weight at all:

      * a QUOTATION is an offer. Nothing is supplied and nothing is owed.
      * a PROFORMA INVOICE is the same offer, formatted so a customer can raise
        a payment or open a letter of credit against it. It is NOT a tax
        invoice and the Act does not know it.
      * a SALES ORDER is the customer's acceptance. CGST s.7 charges a SUPPLY,
        and an order is a promise to make one.

    The fourth is statutory. A DELIVERY CHALLAN is prescribed by CGST Rule 55
    and the rules that govern it live in `domain/gst/delivery_challan.py`, not
    here — this module is the commercial chain and the arithmetic of what is
    still open.

THE THREE THINGS THIS MODULE REFUSES, AND WHY EACH ONE MATTERS

    1. NONE OF THESE DOCUMENTS POSTS A JOURNAL. No revenue has been earned
       (AS-9 / Ind AS 115 recognise revenue on transfer of the significant
       risks and rewards, which an offer does not effect) and no receivable
       exists. A quotation that debited Trade Receivables would put a customer
       in the AR ageing for goods nobody has ordered.

    2. NONE OF THEM REACHES A RETURN. GSTR-1 is built from documents that
       DECLARE a supply — the tax invoice, the notes and the export. A
       proforma is the trap here, because it looks like an invoice and is
       often numbered like one; a GSTR-1 that picked one up would declare a
       supply that never happened and the client would pay tax on it.

    3. A PROFORMA IS NEVER NUMBERED FROM THE TAX-INVOICE SERIES. Rule 46(b)
       requires a tax invoice's serial number to be CONSECUTIVE and unique for
       the financial year. Consuming a number for a document that may never
       become a supply puts a permanent gap in the series the CA then has to
       explain — and if the same number is later used for the real invoice,
       two documents bear it. `series_kind_of` names a separate series per
       kind and the series authority enforces uniqueness per client per kind.

WHAT AN ORDER STILL HAS OPEN IS DERIVED, NEVER STORED
    The same reasoning as migration 278's generated `outstanding_paise`: what
    is left to deliver and what is left to bill are functions of the
    documents raised against the order, and a stored figure is wrong the
    moment one is cancelled or amended. `open_quantities` derives both.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

# ── The four kinds ───────────────────────────────────────────────────────────
#
# Quotation and proforma share ONE table with a `kind` discriminator because
# their particulars, their lines and their lifecycle are identical — only the
# heading and the numbering series differ. That is deliberately NOT the shape
# used for the delivery challan, which carries Rule 55 particulars a quotation
# has no column for.
KIND_QUOTATION = "quotation"
KIND_PROFORMA = "proforma"
QUOTE_KINDS = (KIND_QUOTATION, KIND_PROFORMA)

#: How each kind is titled on the document the customer reads. A proforma MUST
#: say so on its face: a document headed "Invoice" that is not a tax invoice is
#: how a recipient comes to claim credit that does not exist.
KIND_TITLES = {
    KIND_QUOTATION: "Quotation",
    KIND_PROFORMA: "Proforma Invoice",
}

#: The sentence every one of these documents carries. It is not boilerplate:
#: CGST s.31 makes the TAX INVOICE the document a supply is made on, and the
#: recipient's credit under s.16(2)(a) rests on holding one. A customer who
#: files a proforma as an invoice claims credit the supplier never declared.
NOT_A_TAX_INVOICE = (
    "This is not a tax invoice. No supply has been made and no GST is payable "
    "on this document. A tax invoice under CGST Act s.31 is issued when the "
    "goods are supplied or the service is provided."
)

# ── Status vocabularies ──────────────────────────────────────────────────────
#
# Each is CLOSED and each value means one thing. `expired` is derived from the
# date and is NOT stored — a quotation does not become expired by anyone
# doing anything, so a stored status would need a nightly job to stay true
# and would be wrong between runs.
QUOTE_STATUSES = ("draft", "sent", "accepted", "declined", "converted", "cancelled")
ORDER_STATUSES = ("draft", "confirmed", "partially_delivered", "delivered",
                  "closed", "cancelled")
CHALLAN_STATUSES = ("draft", "issued", "received_back", "cancelled")

#: An order in one of these is still live work: it may be delivered against
#: and billed against. The other two are terminal.
ORDER_OPEN_STATUSES = ("confirmed", "partially_delivered")


def series_kind_of(kind: str) -> str:
    """The numbering series a document of this kind draws from.

    One series per KIND, never the tax-invoice series. Rule 46(b) allows "one
    or multiple series" for tax invoices and says nothing about these, so the
    only rule that binds is the one this product imposes on itself:
    uniqueness per client per kind, so two quotations cannot share a number
    and a quotation and an invoice cannot collide.
    """
    k = (kind or "").strip().lower()
    if k in QUOTE_KINDS:
        return f"sales_{k}"
    if k == "sales_order":
        return "sales_order"
    if k == "delivery_challan":
        return "delivery_challan"
    raise ValueError(f"Unknown pre-invoice document kind {kind!r}.")


def is_expired(valid_until: Optional[str], as_at: str) -> Optional[bool]:
    """Whether a quotation's own validity has run out, as at a date.

    `None` means the quotation states no validity, which is NOT the same as
    "still valid": a quotation with no expiry is an offer open indefinitely,
    and whether that is what the client meant is theirs to say. Returning
    False would assert it.
    """
    if not valid_until:
        return None
    return str(valid_until) < str(as_at)


# ── What an order still has open ─────────────────────────────────────────────

@dataclass(frozen=True)
class OpenLine:
    """One order line and what is left of it."""
    order_line_id: str
    description: str
    ordered_qty: Decimal
    delivered_qty: Decimal
    invoiced_qty: Decimal

    @property
    def undelivered_qty(self) -> Decimal:
        return max(Decimal(0), self.ordered_qty - self.delivered_qty)

    @property
    def unbilled_qty(self) -> Decimal:
        return max(Decimal(0), self.ordered_qty - self.invoiced_qty)

    def as_dict(self) -> dict:
        return {
            "order_line_id": self.order_line_id,
            "description": self.description,
            # Quantities cross the wire as strings, for the reason money
            # crosses as integer paise: NUMERIC(10,3) does not survive a
            # float round trip, and 0.1 + 0.2 is not 0.3 in the browser
            # either.
            "ordered_qty": _q(self.ordered_qty),
            "delivered_qty": _q(self.delivered_qty),
            "invoiced_qty": _q(self.invoiced_qty),
            "undelivered_qty": _q(self.undelivered_qty),
            "unbilled_qty": _q(self.unbilled_qty),
        }


def _q(value: Decimal) -> str:
    """A quantity as the column keeps it — three decimals, always."""
    return str(Decimal(value).quantize(Decimal("0.001")))


def to_decimal(value) -> Decimal:
    """A stored quantity, whatever shape PostgREST handed it back in.

    NUMERIC comes back as a STRING from PostgREST and as a Decimal from psycopg;
    `float(x)` on either is the round trip this codebase forbids for money and
    forbids here for the same reason — `Decimal(str(v))`, never `Decimal(v)`
    on a float.
    """
    if value is None:
        return Decimal(0)
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def open_quantities(order_lines: Iterable[dict],
                    delivered_by_line: Optional[dict] = None,
                    invoiced_by_line: Optional[dict] = None) -> list[OpenLine]:
    """Per order line: ordered, delivered, invoiced, and what is left of each.

    DELIVERED AND INVOICED ARE TWO DIFFERENT CLOCKS and an order needs both.
    Goods can be delivered on a challan and billed a month later (Rule 55's
    whole purpose), and a service can be billed in advance of performance. An
    order that tracked only one would show a fully delivered order as open,
    or a fully billed one as undelivered.
    """
    delivered = delivered_by_line or {}
    invoiced = invoiced_by_line or {}
    out: list[OpenLine] = []
    for ln in order_lines or []:
        lid = str(ln.get("id") or "")
        out.append(OpenLine(
            order_line_id=lid,
            description=str(ln.get("description") or ""),
            ordered_qty=to_decimal(ln.get("quantity")),
            delivered_qty=to_decimal(delivered.get(lid)),
            invoiced_qty=to_decimal(invoiced.get(lid)),
        ))
    return out


def order_status_for(lines: Iterable[OpenLine], current: str) -> str:
    """What a confirmed order's status becomes once these deliveries are in.

    Derived from the lines and applied ONLY to an order that is currently
    live: a cancelled or closed order is a decision somebody took and is not
    re-opened by arithmetic. `closed` likewise — a CA closes an order that
    will never be fully delivered (the customer took less than they ordered),
    and recomputing would re-open it on every read.
    """
    if current not in ORDER_OPEN_STATUSES:
        return current
    rows = list(lines)
    if not rows:
        return current
    if all(ln.undelivered_qty == 0 for ln in rows):
        return "delivered"
    if any(ln.delivered_qty > 0 for ln in rows):
        return "partially_delivered"
    return "confirmed"


# ── Over-delivery and over-billing ───────────────────────────────────────────
#
# REFUSED, not clamped. Delivering more than was ordered is either a keying
# error or a real change the customer agreed to — and the second is an amended
# order, not a silent one. Clamping would deliver the ordered quantity and
# lose the excess with no record; allowing it would make the order's own
# figures stop describing the agreement.

def over_delivery(line: OpenLine, quantity: Decimal) -> Optional[str]:
    if quantity <= 0:
        return (f"{line.description}: a delivery must be of a positive "
                f"quantity.")
    if quantity > line.undelivered_qty:
        return (f"{line.description}: {_q(quantity)} is more than the "
                f"{_q(line.undelivered_qty)} still undelivered on this order "
                f"line ({_q(line.ordered_qty)} ordered, "
                f"{_q(line.delivered_qty)} already delivered). Amend the "
                f"order if the customer has agreed to take more.")
    return None


def over_billing(line: OpenLine, quantity: Decimal) -> Optional[str]:
    if quantity <= 0:
        return f"{line.description}: an invoice line must be of a positive quantity."
    if quantity > line.unbilled_qty:
        return (f"{line.description}: {_q(quantity)} is more than the "
                f"{_q(line.unbilled_qty)} still unbilled on this order line "
                f"({_q(line.ordered_qty)} ordered, {_q(line.invoiced_qty)} "
                f"already invoiced).")
    return None


# ── What a conversion carries ────────────────────────────────────────────────

#: The line fields a conversion copies FORWARD, in the order a reader expects
#: them. Deliberately a list rather than "everything on the row": a quotation
#: line carries its own id, its own parent and its own timestamps, and copying
#: those would either collide or silently re-parent the new document.
LINE_FIELDS_CARRIED = (
    "description", "hsn_sac", "quantity", "unit", "rate_paise",
    "gst_rate_percent", "is_service", "service_catalogue_id",
    "discount_percent_bps", "discount_paise",
    "cess_rate_bps", "cess_specific_paise_per_unit",
)

#: Header fields a conversion carries. `place_of_supply` is here and the DATE
#: is not: a quotation raised in March and converted in April is an April
#: supply, and carrying the quotation's date forward would date the invoice
#: into a financial year that may already be closed.
HEADER_FIELDS_CARRIED = (
    "customer_id", "customer_name", "customer_gstin", "place_of_supply",
    "supply_state_code", "is_inter_state", "currency", "notes",
)


def carry_line(line: dict) -> dict:
    """One line, ready to be a line of the next document in the chain."""
    return {f: line.get(f) for f in LINE_FIELDS_CARRIED if line.get(f) is not None}


def carry_header(header: dict) -> dict:
    return {f: header.get(f) for f in HEADER_FIELDS_CARRIED
            if header.get(f) is not None}
