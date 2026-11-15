"""A physical count of a client's fixed assets (POST-A-112, migration 592): which assets it must account for, and its tally.

A count is made on one day, and it accounts for every asset the client HELD on that day: bought on or before it, not deleted, and not
disposed of on or before it. `public.fixed_asset_held_on` says the same in the database (both functions of 592 ask it); this is its
mock-mode twin, pinned to it by `tests/test_592_..._pg.py`.

A finding is one of four, and none of them moves anything in the register: an asset found elsewhere is moved by a movement (591), which
the person records, and a damaged one is a fact for the CA, never an accounting entry made here.
"""
from __future__ import annotations

from typing import Iterable, Optional

#: The four findings, in the order a working paper lists them, with the words a person reads.
FINDINGS: dict[str, str] = {
    "found": "Found where the register has it",
    "found_elsewhere": "Found elsewhere",
    "not_found": "Not found",
    "damaged": "Found damaged",
}


def held_on(asset: dict, day: str) -> bool:
    """Whether the asset was held on `day` (an ISO date): bought on or before it, not deleted, not disposed of on or before it."""
    if asset.get("deleted_at"):
        return False
    bought = str(asset.get("purchase_date") or "")[:10]
    if bought and bought > day:
        return False
    if asset.get("is_disposed"):
        gone = str(asset.get("disposal_date") or "")[:10]
        if not gone or gone <= day:
            return False
    return True


def register_on(asset: dict, movements: Iterable[dict], day: str) -> tuple[Optional[str], Optional[str]]:
    """The place and keeper the register held for the asset on `day`, as `record_fixed_asset_finding` reads them: the "before" of the
    first movement dated after the day (movements are recorded in the order of their dates, 591, so that one carries what the register
    held from the day until it moved), or, where the asset has not moved since, its own place and keeper. Never the place as it is now
    when the asset has moved since the day. Returned as stored; a caller that compares them tidies them first."""
    later = sorted((m for m in movements if m.get("asset_id") == asset.get("id") and str(m.get("moved_on") or "")[:10] > day),
                   key=lambda m: (str(m.get("moved_on") or "")[:10], str(m.get("created_at") or ""), str(m.get("id") or "")))
    if later:
        return later[0].get("from_location"), later[0].get("from_custodian")
    return asset.get("location"), asset.get("custodian")


def tally(findings: Iterable[dict], to_count: Optional[int]) -> dict:
    """How many of each finding, and how many assets held on the day have none yet (`to_count`, None on a closed count, whose record
    is its findings alone)."""
    out = {kind: 0 for kind in FINDINGS}
    for f in findings:
        if f.get("finding") in out:
            out[f["finding"]] += 1
    return {**out, "to_count": to_count}
