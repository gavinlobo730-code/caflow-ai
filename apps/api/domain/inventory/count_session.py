"""A physical stock count is ONE session, and the variance is a fact about the
COUNT DATE (INV-08).

WHAT WAS WRONG
    Stock adjustment was one item per API call and one item per modal, opened
    only from inside an item's ledger drill-down. Stock-taking at 31 March
    produces a sheet with a hundred variances, so the CA opened each item's
    ledger, retyped the quantity, chose a reason and confirmed the s.17(5)(h)
    checkbox — a hundred times — and the hundred journals that came out had no
    common reference tying them to the count.

WHAT THIS MODULE IS, AND IS NOT
    It is the RULE: which lines vary, by how much, in which direction, and
    which of them cannot post yet and why. It reads no database and posts
    nothing. `services/stock_count_service.py` fetches its inputs and
    `routers/inventory.py` posts the answer through
    `domain/inventory_service.apply_stock_adjustment` — the SAME function the
    single-item path uses, once per varying line. One write path.

THE SYSTEM QUANTITY IS ON BOTH SIDES OF TIME, AND ONLY ONE OF THEM DECIDES
    `system_qty_units` on the line is what the books said when the sheet was
    OPENED — what the CA was counting against, kept so they can see that the
    books moved under them. The variance that POSTS is measured against the
    position AS AT THE COUNT DATE, recomputed at post time, because stock
    genuinely moves between opening a sheet and keying it in: a 30 March
    purchase bill entered on 2 April changes what the books say for 31 March,
    and the count is a fact about 31 March. Posting the snapshot's variance
    would re-introduce the very difference the bill corrected. Where the two
    disagree the session SAYS so rather than silently preferring one.

WHAT IT REFUSES
    * a line NOT YET COUNTED — NULL is not zero, and a zero count writes the
      whole of an item's stock off, which is a real answer somebody has to
      give;
    * a SHORTAGE with no s.17(5)(h) decision — whether the credit must be
      reversed is a judgement only the CA can make, since damaged stock might
      still be sold at a discount. A SURPLUS needs no decision: stock found is
      not stock lost, and the single-item path has refused `reverse_itc` on an
      increase since it was written.

    Both are per LINE. A sheet of a hundred with two undecided posts the
    ninety-eight and names the two — refusing the whole batch for two lines
    would send the CA back to the hundred-clicks path they came from.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional

INCREASE = "increase"
DECREASE = "decrease"

#: The two reasons a physical count produces. `models/inventory.ADJUSTMENT_REASONS`
#: is the full set and holds these two; a count can never produce any of the
#: others, so the session never asks.
REASON_SHORTAGE = "physical_count_shortage"
REASON_SURPLUS = "physical_count_surplus"

STATUS_OPEN = "open"
STATUS_POSTED = "posted"
STATUS_ABANDONED = "abandoned"
STATUSES = (STATUS_OPEN, STATUS_POSTED, STATUS_ABANDONED)


@dataclass(frozen=True)
class CountLine:
    """One row of the sheet, with the variance worked out."""
    service_catalogue_id: str
    item_name: str
    unit: Optional[str]
    #: What the books said when the sheet was opened.
    system_qty_units: Decimal
    #: What the books say AS AT THE COUNT DATE, now.
    current_qty_units: Decimal
    counted_qty_units: Optional[Decimal]
    reverse_itc: Optional[bool]
    itc_reversal_is_interstate: bool
    notes: str = ""
    line_id: str = ""

    @property
    def variance_qty_units(self) -> Optional[Decimal]:
        if self.counted_qty_units is None:
            return None
        return self.counted_qty_units - self.current_qty_units

    @property
    def direction(self) -> Optional[str]:
        v = self.variance_qty_units
        if v is None or v == 0:
            return None
        return INCREASE if v > 0 else DECREASE

    @property
    def reason(self) -> Optional[str]:
        d = self.direction
        if d is None:
            return None
        return REASON_SURPLUS if d == INCREASE else REASON_SHORTAGE

    @property
    def books_moved_since_the_sheet_was_opened(self) -> bool:
        return self.current_qty_units != self.system_qty_units


@dataclass(frozen=True)
class LinePlan:
    """What will happen to one line when the session posts."""
    line: CountLine
    will_post: bool
    #: Absolute quantity for `apply_stock_adjustment`, which takes a positive
    #: number and a direction rather than a signed delta.
    quantity: Optional[Decimal]
    direction: Optional[str]
    reason: Optional[str]
    #: Why it will not post. Empty when it will.
    gaps: list[str] = field(default_factory=list)
    caveats: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class CountPlan:
    count_date: str
    reference_no: str
    lines: list[LinePlan] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)

    @property
    def postable(self) -> list[LinePlan]:
        return [p for p in self.lines if p.will_post]

    @property
    def counted_count(self) -> int:
        return sum(1 for p in self.lines if p.line.counted_qty_units is not None)

    @property
    def variance_count(self) -> int:
        return sum(1 for p in self.lines if p.line.direction is not None)

    @property
    def blocked_count(self) -> int:
        return sum(1 for p in self.lines if p.gaps)


def plan(*, count_date: str, reference_no: str, lines: list[CountLine]) -> CountPlan:
    """What this session will post, line by line, and what it will not.

    Pure and total. Every refusal is a sentence rather than an exception,
    because a screen showing a CA a hundred-line sheet needs to say which two
    lines need them and why.
    """
    out: list[LinePlan] = []
    for line in lines:
        out.append(_one(line))
    gaps: list[str] = []
    if not (reference_no or "").strip():
        gaps.append("This count has no reference. It is what ties the "
                    "adjustments to the sheet, so it cannot be blank.")
    if not count_date:
        gaps.append("This count has no date, so no variance can be measured "
                    "and nothing can be posted.")
    return CountPlan(count_date=count_date, reference_no=reference_no,
                     lines=out, gaps=gaps)


def _one(line: CountLine) -> LinePlan:
    caveats: list[str] = []
    if line.books_moved_since_the_sheet_was_opened:
        caveats.append(
            f"The books said {line.system_qty_units} when this sheet was "
            f"opened and say {line.current_qty_units} as at the count date "
            "now. The variance below is against the CURRENT figure, which is "
            "the one the count is a fact about.")

    if line.counted_qty_units is None:
        return LinePlan(line=line, will_post=False, quantity=None, direction=None,
                        reason=None, caveats=caveats,
                        gaps=["Not counted yet. Blank is not zero — a zero "
                              "count writes the whole of this item's stock "
                              "off, which is an answer somebody has to give."])

    variance = line.variance_qty_units
    if variance == 0:
        return LinePlan(line=line, will_post=False, quantity=None, direction=None,
                        reason=None, caveats=caveats)

    direction = line.direction
    gaps: list[str] = []
    if direction == DECREASE and line.reverse_itc is None:
        gaps.append(
            "A shortage needs the CGST Act s.17(5)(h) decision: was the input "
            "tax credit on this stock reversed? It is a judgement — damaged "
            "stock might still be sold at a discount — so it is asked rather "
            "than assumed.")
    if direction == INCREASE and line.reverse_itc:
        gaps.append(
            "s.17(5)(h) reaches goods lost, stolen, destroyed, written off or "
            "given away. A surplus is stock FOUND, so there is no credit to "
            "reverse.")

    return LinePlan(
        line=line, will_post=not gaps,
        quantity=abs(variance), direction=direction, reason=line.reason,
        gaps=gaps, caveats=caveats)
