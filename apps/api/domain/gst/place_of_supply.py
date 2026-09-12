"""
Inter-state or intra-state — IGST Act §§7 and 8, decided on the server.

WHAT WAS WRONG (no finding; found by the 12 September probe pass)
    The GSTR-1 Table 11A advance receipt carried `is_interstate` as a field the
    BROWSER computed and the server stored verbatim:

        is_interstate: advancePos !== clientStateCode

    Two things follow. It is a statutory rule living in the frontend, against
    this codebase's "zero business logic in the frontend" rule — and the same
    receipt form's own comment congratulates itself for deriving a figure
    "rather than asking it as a third question", which it does on the wrong
    side of the wire.

    Worse, `clients.state_code` is nullable and nothing requires it. For a
    client with no state code recorded, `advancePos !== ""` is true for every
    place of supply, so EVERY advance was declared inter-state — IGST in Table
    11A where CGST and SGST were due, on a return the CA files.

    The sales-invoice path has always derived this server-side. This is that
    same rule, in one place, for every path that needs it.

WHY IT CAN REFUSE
    §8(1) makes a supply intra-state where the supplier's location and the
    place of supply are in the SAME state, and §7(1) inter-state where they are
    not. Both limbs need the supplier's own state, so where the client's state
    is not known the question has no answer — and answering it anyway is what
    put IGST on a Maharashtra-to-Maharashtra advance.

    `None` is that refusal, and it is not a silence: `gst_advance_service`
    already has an "undeclarable" branch that names an advance it cannot
    declare, and an undecided treatment belongs in it beside a missing rate.
"""
from __future__ import annotations

from typing import Optional

from domain.gst.gstin import state_code as _state_code_of_gstin


def _VALID_STATE_CODES():
    """Imported lazily — `domain/gst/validator` imports back into this package,
    and a module-level import here closes the cycle."""
    from domain.gst.validator import VALID_STATE_CODES
    return VALID_STATE_CODES


def supplier_state_code(client: Optional[dict]) -> Optional[str]:
    """The client's OWN state — the "location of the supplier" of §§7-8.

    The GSTIN first, because CGST §25 makes its first two characters the
    registration's state and a registered client therefore always carries it;
    `clients.state_code` second, for an unregistered client who has one
    recorded. Neither is required by the schema, so both can be absent.
    """
    c = client or {}
    from_gstin = _state_code_of_gstin((c.get("gstin") or "").strip().upper())
    if from_gstin:
        return from_gstin
    code = (c.get("state_code") or "").strip()
    return code or None


def is_interstate(client: Optional[dict], place_of_supply: Optional[str]) -> Optional[bool]:
    """True, False, or None when the question cannot be answered.

    IGST §8(1): same state as the supplier → intra-state. §7(1): otherwise →
    inter-state. `None` where either side is unknown, so a caller stores the
    unknown rather than a default that is wrong half the time.
    """
    pos = (place_of_supply or "").strip()
    supplier = supplier_state_code(client)
    if not pos or not supplier:
        return None
    return pos != supplier


# ── Which state the supply is MADE TO ────────────────────────────────────────
#
# WHAT WAS WRONG (SALES-31)
#
#     The four-source chain below was an inline expression in
#     `routers/sales_invoices.py`, and the mock branch six lines above it
#     resolved the same question DIFFERENTLY: mock read
#     `place_of_supply or supply_state_code`, the real path read only
#     `supply_state_code`. `SalesInvoiceIn` declares both fields and documents
#     `place_of_supply` as "2-digit state code".
#
#     So a caller who filled in `place_of_supply` and not `supply_state_code`
#     got their answer honoured under test and silently discarded in
#     production — where the chain then fell through to the customer's state,
#     or to the client's own, and produced CGST+SGST on an inter-state supply.
#     A divergence between mock and real is the one kind of defect a test
#     suite structurally cannot see, which is why the resolution now lives here
#     and both branches call it.
#
#     `place_of_supply` also had no validator, while `ReceiptIn`'s copy of the
#     same field has had one since GST-15. A place of supply that is not a
#     state code puts the invoice in the wrong GSTR-1 bucket.

#: Where a resolved place of supply came from. Returned beside the code because
#: "27 because the customer's GSTIN says so" and "27 because the supplier is
#: there and we know nothing about the recipient" are different facts, and only
#: the second is a statutory default a CA might want to override.
SOURCE_STATED = "stated"
SOURCE_CUSTOMER_STATE = "customer_state"
SOURCE_CUSTOMER_GSTIN = "customer_gstin"
SOURCE_SUPPLIER_STATE = "supplier_state"
SOURCE_UNKNOWN = "unknown"


def recipient_place_of_supply(
    *,
    stated: Optional[str],
    customer: Optional[dict],
    supplier_state: Optional[str],
) -> tuple[str, str]:
    """(code, source) — the place of supply for a sale, in statutory order.

    1. WHAT THE CALLER SAID. A place of supply typed on the invoice is the
       document's own particular under CGST Rule 46(n) and outranks anything
       derived.
    2. THE CUSTOMER'S RECORDED STATE.
    3. THE CUSTOMER'S GSTIN. CGST §25 makes its first two characters the
       registration's state, so a REGISTERED customer always carries their own
       place of supply whether or not anybody filled the field in. It is free
       and it is the best source where the state code is blank.
    4. THE SUPPLIER'S OWN STATE. IGST §12(2)(b)(ii): where the recipient is
       unregistered and no address is on record, the place of supply is the
       location of the supplier. That is the ordinary over-the-counter B2C
       sale, and it is a RULE rather than a guess — without it, requiring a
       place of supply at issue would block billing a walk-in customer, which
       is most of a retail client's day.

    `("", SOURCE_UNKNOWN)` when even the supplier's state is not known, which
    is a real state of the data: `clients.gstin` is nullable.
    """
    said = (stated or "").strip()
    if said:
        return said, SOURCE_STATED
    c = customer or {}
    from_state = (c.get("state_code") or "").strip()
    if from_state:
        return from_state, SOURCE_CUSTOMER_STATE
    # THE PREFIX, not `gstin.state_code`. That function requires a fully valid
    # GSTIN — check digit included — and the question here is WHICH STATE, not
    # whether the registration number is well-formed. A customer master GSTIN
    # with a bad check digit still names its state, and falling through to the
    # supplier's would silently turn an inter-state supply intra-state, which
    # is the error this whole resolver exists to stop. The check-digit guard
    # belongs where a human TYPES a GSTIN — onboarding, the customer and vendor
    # create, bulk-import and PATCH paths — and CLAUDE.md records why the
    # Pydantic field is deliberately not it.
    #
    # Validated against the state list all the same, so a truncated or garbage
    # value cannot become a place of supply.
    from_gstin = (c.get("gstin") or "").strip().upper()[:2]
    if from_gstin in _VALID_STATE_CODES():
        return from_gstin, SOURCE_CUSTOMER_GSTIN
    supplier = (supplier_state or "").strip()
    if supplier:
        return supplier, SOURCE_SUPPLIER_STATE
    return "", SOURCE_UNKNOWN
