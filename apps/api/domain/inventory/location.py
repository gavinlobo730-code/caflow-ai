"""Where the stock is — godowns, and the one GST consequence of moving it
(INV-03a, migration 398).

WHY A GODOWN IS NOT DECORATION

CGST s.25(1) requires registration in EVERY State or Union territory from which
a taxable supply is made, and s.25(2)'s proviso allows a separate registration
per place of business within one state. Migration 390 gave a client several
GSTINs for exactly that. A warehouse in another state is one of those places,
so a godown carries its own state and, where the client holds several, the
registration it operates under.

AND MOVING STOCK BETWEEN TWO OF THEM MAY BE A SUPPLY

    Schedule I paragraph 2: "Supply of goods or services or both between
    related persons or between DISTINCT PERSONS as specified in section 25,
    when made in the course or furtherance of business" is treated as a supply
    EVEN IF MADE WITHOUT CONSIDERATION.

s.25(4) makes two registrations of one entity distinct persons. So a transfer
from a Maharashtra godown under 27XXXXX to a Karnataka godown under 29XXXXX is
a taxable supply needing a tax invoice; a transfer between two godowns under
the SAME registration is not a supply at all and is a movement of the client's
own goods from one shelf to another.

THIS MODULE STATES THAT AND REFUSES TO ACT ON IT. It does not mint the invoice,
because the VALUE of such a supply is s.15 read with Rule 28 — open market
value, or the value of goods of like kind and quality, or 90% of the price the
recipient charges on, at the supplier's own option, with the second proviso
allowing ANY declared value where the recipient is eligible for full credit —
and which of those a client elects is a decision nothing here holds. Naming it
puts the question in front of the CA; guessing it files a return on a figure
nobody chose.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Optional

#: A movement with no godown recorded. Every movement made before migration 398
#: has one, and NULL is a real group in every report rather than a row to drop.
UNALLOCATED = "unallocated"
UNALLOCATED_LABEL = "Not allocated to a godown"

UNALLOCATED_MEANS = (
    "These movements were recorded before this client had godowns, or without "
    "one being chosen. They are not lost — they are in the total, and the total "
    "still ties to the Inventory control account — but nobody recorded where "
    "they happened, so they cannot be shown at a location. Nothing is "
    "back-filled: stamping a default godown on them would assert they all "
    "happened there."
)

#: Schedule I paragraph 2 with s.25(4). The exact sentence a CA needs, and the
#: reason this module goes no further.
INTERSTATE_TRANSFER_IS_A_SUPPLY = (
    "These two godowns operate under different GST registrations, which CGST "
    "s.25(4) makes distinct persons — so Schedule I paragraph 2 treats this "
    "movement as a supply even though no money changes hands, and it needs a "
    "tax invoice. This software does not raise it: the value is s.15 with Rule "
    "28 (open market value, the value of like goods, or 90% of the recipient's "
    "onward price, at the supplier's option — and any declared value where the "
    "recipient may take full credit), and which of those the client elects is "
    "not recorded anywhere here."
)

SAME_REGISTRATION_IS_NOT_A_SUPPLY = (
    "Both godowns operate under the same GST registration, so this is a "
    "movement of the client's own goods and not a supply. No invoice and no "
    "return entry arises; a delivery challan under CGST Rule 55(1)(c) is the "
    "document for the transport."
)

REGISTRATION_NOT_RECORDED = (
    "One or both of these godowns has no GST registration recorded against it, "
    "so whether this movement is a supply between distinct persons cannot be "
    "determined. Record the registration each godown operates under — CGST "
    "s.25(1) requires one per State a taxable supply is made from."
)


@dataclass(frozen=True)
class Godown:
    godown_id: str
    name: str
    state_code: Optional[str] = None
    gstin: Optional[str] = None
    is_default: bool = False
    is_active: bool = True


@dataclass
class TransferDecision:
    """Whether a stock transfer between two godowns is a supply.

    THREE STATES, NOT TWO. `is_supply` is True, False or None, and None is the
    answer where a registration is not recorded — the same tri-state
    `vendors.gst_registration_status` uses, and for the same reason: one guess
    mints a tax invoice the Act does not ask for and the other omits one it
    does.
    """
    is_supply: Optional[bool]
    reason: str
    same_registration: Optional[bool] = None
    gaps: list = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "is_supply": self.is_supply,
            "reason": self.reason,
            "same_registration": self.same_registration,
            "gaps": list(self.gaps),
        }


def transfer_decision(source: Godown, destination: Godown) -> TransferDecision:
    """Is moving stock from `source` to `destination` a supply?"""
    if source.godown_id == destination.godown_id:
        return TransferDecision(
            is_supply=False,
            reason="Source and destination are the same godown.",
            same_registration=True)

    if not source.gstin or not destination.gstin:
        return TransferDecision(
            is_supply=None, reason=REGISTRATION_NOT_RECORDED,
            same_registration=None, gaps=[REGISTRATION_NOT_RECORDED])

    # COMPARED AS REGISTRATIONS, not as states. Two godowns in one state under
    # one registration are the same person; the state code is derived FROM the
    # registration (its first two characters) and comparing states instead
    # would call a second registration in the same state — which s.25(2)'s
    # proviso expressly allows — a non-supply.
    same = source.gstin.strip().upper() == destination.gstin.strip().upper()
    return TransferDecision(
        is_supply=not same,
        reason=(SAME_REGISTRATION_IS_NOT_A_SUPPLY if same
                else INTERSTATE_TRANSFER_IS_A_SUPPLY),
        same_registration=same)


def default_godown(godowns: Iterable[Godown]) -> Optional[Godown]:
    """The one marked default, or the only active one, or None.

    NEVER "the first": a movement landing in whichever godown happened to sort
    first is a position nobody can explain later. Where a client has several
    and has marked none, this returns None and the caller asks.
    """
    live = [g for g in godowns if g.is_active]
    marked = [g for g in live if g.is_default]
    if marked:
        return marked[0]
    if len(live) == 1:
        return live[0]
    return None


def refusal_for(godowns: Iterable[Godown], chosen_id: Optional[str]) -> Optional[str]:
    """Why this godown cannot take a movement, or None.

    A CLIENT WITH NO GODOWNS IS FINE. The columns are nullable and every
    movement before migration 398 has none, so requiring one would break the
    ordinary path for every client who does not keep stock in more than one
    place. The refusals are about a godown that was NAMED and is wrong.
    """
    if chosen_id is None:
        return None
    match = next((g for g in godowns if g.godown_id == chosen_id), None)
    if match is None:
        return "That godown is not one of this client's."
    if not match.is_active:
        return (f"{match.name} is closed. Stock cannot move into or out of a "
                f"closed godown — reopen it, or choose another.")
    return None
