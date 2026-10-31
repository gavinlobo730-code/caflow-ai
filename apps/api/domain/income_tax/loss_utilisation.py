"""What a brought-forward loss has LEFT, and what filing a return uses of it (POST-A-073, IT-10's other half).

`brought_forward_losses` carries one running total, `utilized_amount_paise`, and `remaining_amount_paise` beside it. Nothing ever wrote
either when a return was filed, so next year's computation reloaded the whole loss unless the CA edited it by hand. Writing the total back
is not enough, and the way it goes wrong is quiet: the computation screen offers `remaining_amount_paise`, so once a year's return has used
a loss, RECOMPUTING THAT SAME YEAR (a revised return under section 139(5), or a CA reopening the computation) would offer the loss net of
its own earlier use and understate the relief in the revised return. A wrong number where today there is none.

So the use is recorded PER FILING AND PER FINANCIAL YEAR, in `utilisations`:

    { "<filing id>": { "financial_year": "2025-26", "amount_paise": 4000000, "return_type": "original" } }

and the two totals become caches of it:

    utilized  = baseline + sum(amount of every entry)
    remaining = original - utilized

`baseline` is whatever was recorded by hand through `utilize_bf_loss` (the one route that moves the total with no filing behind it). It is never
stored: it is `utilized - sum(entries)`, so a hand edit and a filing cannot disagree about it, and the rule below leaves it exactly as found.

WHAT A COMPUTATION MAY USE is the loss less the uses of OTHER years: `remaining` plus whatever THIS year's filings already took. Computing
2025-26 again offers back the 2025-26 use and keeps every other year's.

A REVISED RETURN REPLACES THE ORIGINAL'S USE FOR THE SAME YEAR. The write is keyed by (filing, year) and removes the entries of that year that
belong to other filings, because a revised return is the return for the year; adding its use to the original's would count one year's relief
twice. Entries of OTHER years are never touched by a write. [S]: that a revised return (section 139(5)) stands in the place of the original for
the year is how `domain/income_tax/return_type.py` already treats it (it "RE-DECLARES a year already declared"), and it is not read from the Act
here (owner-list S21).

THE ORDER OF ACKNOWLEDGEMENT IS NOT THE ORDER OF THE RETURNS. A revised return can be acknowledged first and the original it replaced after (the
original stays at ready-for-filing until somebody records it), and replacing by arrival order would let the superseded original overwrite the return
that stands. Each entry therefore carries the kind of return that wrote it, an original never replaces a revised return's entry for the same year
(`Superseded`), and a revised return replaces whatever the year holds.

Nothing here reads a database. The functions take a row and return the columns to store, so the same rule serves the compute route, the filing
write-back and a real-Postgres test, and none of them can drift from the others.
"""
from __future__ import annotations

from typing import Any, Mapping, Optional


#: Which kind of return stands over which, for the same financial year. A higher kind replaces a lower one and a lower one never replaces a
#: higher one. `updated` is absent on purpose: nothing writes an updated return's use (owner-list S21).
_RANK = {"original": 0, "revised": 1}


class Superseded(ValueError):
    """A return of a lower kind was asked to replace the entry of a higher one for the same year. `by` is the filing id that holds it."""

    def __init__(self, by: str):
        super().__init__(f"the use for this year is held by return {by}, which stands over this one")
        self.by = by


def _paise(value: Any) -> int:
    """A stored integer count of paise; anything else is 0 (a missing or NULL column is not a negative)."""
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def entries_of(row: Mapping[str, Any]) -> dict[str, dict]:
    """The row's per-filing uses, tolerant of a row that predates the column (migration 567) or a value that is not an object."""
    raw = row.get("utilisations")
    if not isinstance(raw, Mapping):
        return {}
    out: dict[str, dict] = {}
    for filing_id, entry in raw.items():
        if not isinstance(entry, Mapping):
            continue
        fy = str(entry.get("financial_year") or "").strip()
        if not fy:
            continue
        kind = str(entry.get("return_type") or "original").strip().lower()
        out[str(filing_id)] = {"financial_year": fy, "amount_paise": _paise(entry.get("amount_paise")),
                               "return_type": kind if kind in _RANK else "original"}
    return out


def baseline_paise(row: Mapping[str, Any]) -> int:
    """What was recorded by hand: the stored total less every filing's entry. Never below zero."""
    return max(0, _paise(row.get("utilized_amount_paise")) - sum(e["amount_paise"] for e in entries_of(row).values()))


def used_in_year_paise(row: Mapping[str, Any], financial_year: str) -> int:
    """What filings for `financial_year` have already taken of this loss."""
    fy = (financial_year or "").strip()
    return sum(e["amount_paise"] for e in entries_of(row).values() if e["financial_year"] == fy)


def _year_start(financial_year: str) -> int | None:
    """The calendar year a financial-year label starts in (`2026-27` -> 2026), or None for a label that does not begin with four digits."""
    head = (financial_year or "").strip()[:4]
    return int(head) if len(head) == 4 and head.isdigit() else None


def is_earlier_year(financial_year: str, than: str) -> bool:
    """True when `financial_year` starts in an earlier year than `than`. A label that cannot be read is neither earlier nor later."""
    a, b = _year_start(financial_year), _year_start(than)
    return a is not None and b is not None and a < b


def later_uses(row: Mapping[str, Any], financial_year: str) -> list[dict]:
    """The returns for years AFTER `financial_year` that have already taken part of this loss, oldest year first (POST-A-367).

    `available_for_year_paise` leaves these out, which is right for the year's own revised return and understates what an EARLIER year could
    have had: using more of the loss now may mean the later return has to be revised. This only reports the record's arithmetic; which year
    should have had the loss first is not decided here. Each item is `{"filing_id", "financial_year", "amount_paise", "return_type"}`.
    """
    found = [
        {"filing_id": fid, "financial_year": e["financial_year"], "amount_paise": e["amount_paise"], "return_type": e["return_type"]}
        for fid, e in entries_of(row).items()
        if e["amount_paise"] > 0 and is_earlier_year(financial_year, e["financial_year"])
    ]
    return sorted(found, key=lambda item: (_year_start(item["financial_year"]) or 0, item["filing_id"]))


def uses_view(row: Mapping[str, Any], filings: Optional[Mapping[str, Mapping[str, Any]]]) -> dict:
    """Where a loss went, as a screen shows it (POST-A-368): the part recorded by hand and one item per filing's use, oldest year first.

    `filings` maps a filing id to its row. `None` means the filings could not be read, and then an item says nothing about whether its return is
    still on file (`filing_found` is `None`, and so is the acknowledgement number): a failed read must not be worded as a return that is gone.
    An item whose return is not among the readable filings says `filing_found: False`. Nothing is added up here that the record does not
    already hold: the hand-recorded part is the stored total less the entries (`baseline_paise`), and an entry of no rupees is not a use.
    Each item is `{"filing_id", "financial_year", "return_type", "amount_paise", "filing_found", "acknowledgement_number"}`."""
    items = []
    for fid, e in entries_of(row).items():
        if e["amount_paise"] <= 0:
            continue
        filing = None if filings is None else filings.get(fid)
        ack = (filing or {}).get("acknowledgement_number")
        items.append({
            "filing_id": fid, "financial_year": e["financial_year"], "return_type": e["return_type"], "amount_paise": e["amount_paise"],
            "filing_found": None if filings is None else filing is not None,
            "acknowledgement_number": str(ack) if ack else None,
        })
    items.sort(key=lambda item: (_year_start(item["financial_year"]) or 0, item["filing_id"]))
    return {"hand_recorded_paise": baseline_paise(row), "uses": items}


def holds_entry_for(row: Mapping[str, Any], filing_id: str, financial_year: str, return_type: str = "original") -> bool:
    """True when the record already shows the use of `financial_year` that `filing_id` made, or shows it as held by a return that stands over
    it (a revised return replaced an original's entry, so the original's own id is rightly absent)."""
    fy = (financial_year or "").strip()
    kind = return_type if return_type in _RANK else "original"
    for fid, e in entries_of(row).items():
        if e["financial_year"] != fy:
            continue
        if fid == str(filing_id) or _RANK[e["return_type"]] >= _RANK[kind]:
            return True
    return False


def available_for_year_paise(row: Mapping[str, Any], financial_year: str) -> int:
    """What a computation for `financial_year` may set off: the loss less the uses of OTHER years.

    `remaining` is already net of every year, so this year's own use is put back. It cannot exceed the loss itself, and a row whose stored
    totals are inconsistent (a use larger than the original, which the CHECK-less column allows) never offers more than the original.
    """
    original = _paise(row.get("original_amount_paise"))
    remaining = _paise(row.get("remaining_amount_paise"))
    return min(original, remaining + used_in_year_paise(row, financial_year))


def after_filing(row: Mapping[str, Any], filing_id: str, financial_year: str, used_paise: int, return_type: str = "original") -> dict:
    """The columns to store once the return `filing_id`, of kind `return_type`, for `financial_year`, has used `used_paise` of this loss.

    - this filing's entry is set to `used_paise`. An ORIGINAL that used nothing has no entry. A REVISED return keeps an entry even when it used
      nothing, because that entry is what stops the original, acknowledged later, from writing over it;
    - every other filing's entry for the SAME year is removed, because the revised return replaces the original's use, EXCEPT that an
      original never replaces a revised return's entry (`Superseded` is raised and nothing is computed);
    - entries of other years are untouched;
    - the use is capped at what the computation could have offered, so an inflated figure in a stored snapshot cannot take more than was
      there, and the totals can never exceed the original (the caller compares the recorded entry with `used_paise` to say so);
    - `utilized` and `remaining` are recomputed from the baseline and the entries, so they are a cache of them, written together.
    """
    fy = (financial_year or "").strip()
    fid = str(filing_id)
    kind = return_type if return_type in _RANK else "original"
    original = _paise(row.get("original_amount_paise"))
    entries = {k: dict(v) for k, v in entries_of(row).items()}
    for other, entry in entries.items():
        if other != fid and entry["financial_year"] == fy and _RANK[entry["return_type"]] > _RANK[kind]:
            raise Superseded(other)
    baseline = baseline_paise(row)
    entries = {k: v for k, v in entries.items() if v["financial_year"] != fy or k == fid}
    entries.pop(fid, None)
    other_years = sum(e["amount_paise"] for e in entries.values())
    room = max(0, original - baseline - other_years)
    use = min(_paise(used_paise), room)
    if use > 0 or kind == "revised":
        entries[fid] = {"financial_year": fy, "amount_paise": use, "return_type": kind}
    utilized = baseline + sum(e["amount_paise"] for e in entries.values())
    return {
        "utilisations": entries,
        "utilized_amount_paise": utilized,
        "remaining_amount_paise": max(0, original - utilized),
    }
