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
