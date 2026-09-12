"""
How long an e-way bill is valid for — Rule 138(10) of the CGST Rules.

WHAT WAS WRONG (SALES-28)
    `ewb_valid_upto` arrives on `RecordEWBGeneratedRequest` as a string the CA
    TYPES, re-keyed off the portal. `distance_km` is captured on
    `GenerateEWBRequest`, stored by migration 156, and read by nothing. So the
    validity the product holds is whatever somebody copied by hand, and the one
    input that determines it sits unused beside it.

    That matters because an expired e-way bill is not a paperwork problem: the
    consignment is liable to detention and the goods and conveyance to seizure
    under §129. A CA who cannot see a bill about to expire cannot extend it,
    and Rule 138(10)'s own proviso allows extension only within eight hours
    either side of expiry.

THE RULE
    Rule 138(10), as amended by Notification 94/2020-Central Tax with effect
    from 01-01-2021:

      * ordinary cargo — one day for the first 200 km, and one further day for
        every 200 km "or part thereof" after that;
      * Over Dimensional Cargo, and multimodal movement where one leg is by
        ship — one day for the first 20 km, and one further day for every 20 km
        or part thereof. Only the ODC half is decided here; the ship half
        cannot be, and SHIP_MULTIMODAL_CAVEAT below says why.

    "One day" is not twenty-four hours. The Explanation to the rule counts a
    day as the period expiring at MIDNIGHT of the day immediately following the
    date of generation, so a bill generated at 23:55 has almost none of its
    first day left. Computing it as `generated + 24h` overstates validity on
    every bill and understates it on none — the direction that gets a lorry
    detained.

⚠️  GRADE [S] — WRITTEN FROM KNOWLEDGE, NOT FROM THE RULE ITSELF.
    This environment's egress proxy refuses cbic.gov.in and every .gov.in
    (see docs/audits/2026-09-07-market-research/), so the 200 km slab, the
    20 km ODC slab and the midnight Explanation could not be read from the
    source. They are stated here in one place, with the notification that
    changed them, precisely so a single edit corrects them if any is wrong —
    and `validity_source` is returned beside every answer so a screen can say
    the figure is computed rather than authoritative. The pre-2021 slab was
    100 km, so a wrong reading here fails in a KNOWN direction: too generous,
    never too strict. Verify against Rule 138(10) before relying on it for a
    consignment.

WHAT THIS DELIBERATELY DOES NOT DO
    It does not decide whether an e-way bill is REQUIRED — that is
    `domain/gst/eway.py`, which measures the consignment value against the
    ₹50,000 threshold of Rule 138(1). Nor does it extend a bill: Rule 138(10)'s
    proviso allows that only in a narrow window around expiry and only by the
    transporter on the portal, so it is a fact to record, never an action to
    take here.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

#: Rule 138(10) — km covered by the first day, and by each further day.
ORDINARY_SLAB_KM = 200
#: Over Dimensional Cargo, and multimodal movement with a leg by ship.
ODC_SLAB_KM = 20

#: THE VALUE THE DATABASE ACTUALLY HOLDS. `eway_bill_records.vehicle_type` is
#: CHECK-constrained to 'regular' or 'over_dimensional' (migration 156, restated
#: in 319), which is the portal's own Regular/Over Dimensional Cargo choice. An
#: earlier draft of this module matched on invented spellings — 'odc',
#: 'over_dimensional_cargo' — and would have silently given every ODC
#: consignment the 200 km slab while looking as though it handled them.
ODC_VEHICLE_TYPE = "over_dimensional"

#: What to tell a reader about where the figure came from. Returned on every
#: answer, so no screen can present a computed date as the portal's own.
VALIDITY_SOURCE_COMPUTED = "computed from distance under Rule 138(10)"

#: THE SHIP CASE IS NOT DECIDED HERE, AND THE ERROR DIRECTION IS WHY.
#: The 20 km slab reaches ODC "or multimodal shipment in which at least one leg
#: involves transport by ship". `transport_mode` holds ONE mode ('road', 'rail',
#: 'air', 'ship'), so a ship leg of a multimodal movement and a movement wholly
#: by ship are the same row. Taking the 20 km slab yields MORE days, so guessing
#: multimodal on a movement that was not would show a CA a bill as live after it
#: expired — and an expired e-way bill is §129 detention, not paperwork. The
#: literal reading agrees: a single-mode ship movement is not multimodal. So the
#: ordinary slab applies and the caveat below is returned beside the answer.
SHIP_MULTIMODAL_CAVEAT = (
    "Computed on the ordinary 200 km slab. If this movement is multimodal with a "
    "leg by ship, Rule 138(10) gives it the 20 km slab and more days than shown — "
    "take the expiry from the portal.")


@dataclass(frozen=True)
class EwayValidity:
    days: int
    valid_upto: datetime
    slab_km: int
    source: str = VALIDITY_SOURCE_COMPUTED
    caveat: Optional[str] = None


def slab_km_for(vehicle_type: Optional[str] = None) -> int:
    """The km slab Rule 138(10) gives this consignment.

    Keyed on the stored `vehicle_type` rather than a boolean, because the portal
    asks for a vehicle TYPE and a caller passing the value it already holds
    cannot get the polarity backwards. Anything that is not the ODC value —
    including None — takes the ordinary slab, which is the direction that cannot
    overstate validity.
    """
    return ODC_SLAB_KM if (vehicle_type or "").strip().lower() == ODC_VEHICLE_TYPE else ORDINARY_SLAB_KM


def days_for(distance_km: int, *, vehicle_type: Optional[str] = None) -> int:
    """Days of validity for a distance, under Rule 138(10).

    One day for the first slab and one for every part-slab after it, which is
    `ceil(distance / slab)` with a floor of 1 — a zero or negative distance is
    still a movement, and the rule grants no bill less than one day.
    """
    slab = slab_km_for(vehicle_type)
    km = int(distance_km or 0)
    if km <= 0:
        return 1
    # Ceiling division on integers — no float, for the same reason money never
    # uses one: 600/200 must be exactly 3, not 2.9999999999999996.
    return max(1, -(-km // slab))


def validity_for(distance_km: int, generated_at: datetime, *,
                 vehicle_type: Optional[str] = None,
                 transport_mode: Optional[str] = None) -> EwayValidity:
    """When a bill generated at `generated_at` expires.

    MIDNIGHT, per the Explanation, not a rolling 24 hours: the first day ends
    at 00:00 on the day after generation, and each further day adds another
    calendar day. Generation at 23:55 therefore leaves five minutes of the
    first day, which is what the rule says and what the portal does.
    """
    days = days_for(distance_km, vehicle_type=vehicle_type)
    slab = slab_km_for(vehicle_type)
    # Midnight ENDING the day of generation, then one midnight per day granted.
    first_midnight = datetime.combine(generated_at.date() + timedelta(days=1),
                                      datetime.min.time(), tzinfo=generated_at.tzinfo)
    caveat = (SHIP_MULTIMODAL_CAVEAT
              if slab == ORDINARY_SLAB_KM and (transport_mode or "").strip().lower() == "ship"
              else None)
    return EwayValidity(days=days,
                        valid_upto=first_midnight + timedelta(days=days - 1),
                        slab_km=slab, caveat=caveat)


def expiry_gap(distance_km: Optional[int]) -> Optional[str]:
    """Why validity could not be computed for this bill, or None.

    Distance is the only input the rule takes, and it is optional on
    `GenerateEWBRequest`. Without it the answer is refused rather than guessed:
    a validity presented as known and wrong is what gets a consignment
    detained, and the CA can read the real date off the portal.
    """
    if distance_km is None or int(distance_km or 0) <= 0:
        return ("The distance was not recorded, so this bill's validity cannot be "
                "computed under Rule 138(10). Take the expiry date from the portal, "
                "or record the distance and it will be worked out here.")
    return None
