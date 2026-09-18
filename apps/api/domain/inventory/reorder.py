"""
What is at or below its reorder level, grouped by item group.

WHY THIS EXISTS (INV-03's other two conveniences)

    `service_catalogue.category` has been a free-text grouping since migration
    180 and NOTHING has ever grouped by it — so a CA who filled it in for
    every item got no report out of it, which is the `capital_wip` shape a
    third time. And there was no reorder level at all, so the one question a
    stock master exists to answer between counts — *what do I need to buy* —
    had to be answered by reading the register item by item.

    Neither is statutory. Nothing here reaches a return, a journal or a stock
    movement, and a test asserts it: this module computes a PROMPT.

A LEVEL THAT IS NOT RECORDED IS ITS OWN ANSWER, NEVER ZERO

    Nullable with no default, and `NOT_SET` is a state of its own. Zero is a
    real and common answer — "tell me when it runs out" — so reading an absent
    level as zero would silently say the CA has made a decision they have not,
    and every item would sit quietly in the "above" bucket for ever. The items
    with no level are COUNTED and NAMED, the same reasoning
    `vendors.msme_status` and `fixed_assets.rule_43_use` take about a fact
    nobody has recorded.

AT THE LEVEL IS BELOW IT

    The test is `on_hand <= level`, because a reorder level is the point at
    which you reorder — a strict `<` would hold the order until the item is
    already short. An item whose on-hand figure is NEGATIVE (oversold, which
    `record_stock_out` permits and absorbs) is below every level including
    zero, and falls out of the same comparison with no special case.

THE ON-HAND FIGURE IS THE LEDGER'S, NOT THE CACHE'S

    The caller passes positions from `stock_position_service.position`, which
    sums `inventory_stock_ledger`'s deltas. `service_catalogue.stock_qty_units`
    is documented in migration 188 as a CACHED running total whose
    authoritative source is the ledger, and a purchasing prompt computed off a
    drifted cache is wrong in the direction that costs money — it says there is
    stock there is not.

AN UNRECORDED GROUP IS ITS OWN GROUP

    `NOT_GROUPED` is a row, never folded into another and never dropped, so a
    client who has half-filled `category` gets the half they can act on and is
    told about the rest. Groups are matched on a case-and-space-folded key —
    "Raw Material" and "raw  material" are one group — and the label shown is
    the first spelling seen, because the CA typed it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Optional

#: The state of one item against its own level. `NOT_SET` is not a degree of
#: the others — it says nobody has decided — so it is never ordered among them.
BELOW = "below"
AT = "at"
ABOVE = "above"
NOT_SET = "not_set"

NOT_GROUPED = "(no item group recorded)"

NO_LEVEL_RECORDED = (
    "No reorder level is recorded for this item, so nothing here says whether "
    "the quantity on hand is enough. An absent level is not zero.")


def _decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return d if d.is_finite() else None


def _group_key(category: Optional[str]) -> str:
    return " ".join((category or "").split()).lower()


@dataclass
class ReorderLine:
    item_id: str
    name: str
    unit: Optional[str]
    group: str
    on_hand_units: Decimal
    reorder_level_units: Optional[Decimal]
    state: str
    shortfall_units: Decimal = Decimal(0)
    note: Optional[str] = None


@dataclass
class ReorderGroup:
    group: str
    lines: list = field(default_factory=list)
    below_count: int = 0
    not_set_count: int = 0


def assess(items, positions) -> dict:
    """One answer per good, bucketed by item group.

    `items` is the catalogue rows (dicts); `positions` maps item id to the
    on-hand quantity the ledger gives. An item the position map does not
    mention is on hand NIL rather than skipped — an item that has never moved
    is exactly the one a reorder level is about.
    """
    lines: list = []
    for row in items or []:
        if (row.get("kind") or "service") != "good":
            continue
        if row.get("is_active") is False:
            continue
        item_id = str(row.get("id") or "")
        on_hand = _decimal(positions.get(item_id)) if positions else None
        if on_hand is None:
            on_hand = Decimal(0)
        level = _decimal(row.get("reorder_level_units"))

        if level is None:
            state, shortfall, note = NOT_SET, Decimal(0), NO_LEVEL_RECORDED
        elif on_hand < level:
            state, shortfall, note = BELOW, level - on_hand, None
        elif on_hand == level:
            state, shortfall, note = AT, Decimal(0), None
        else:
            state, shortfall, note = ABOVE, Decimal(0), None

        label = (row.get("category") or "").strip() or NOT_GROUPED
        lines.append(ReorderLine(
            item_id=item_id,
            name=row.get("name") or "",
            unit=row.get("unit"),
            group=label,
            on_hand_units=on_hand,
            reorder_level_units=level,
            state=state,
            shortfall_units=shortfall,
            note=note,
        ))

    groups: dict = {}
    labels: dict = {}
    for line in lines:
        key = _group_key(line.group) or _group_key(NOT_GROUPED)
        labels.setdefault(key, line.group)
        line.group = labels[key]
        g = groups.setdefault(key, ReorderGroup(group=labels[key]))
        g.lines.append(line)
        if line.state in (BELOW, AT):
            g.below_count += 1
        elif line.state == NOT_SET:
            g.not_set_count += 1

    ordered = sorted(groups.values(),
                     key=lambda g: (g.group == NOT_GROUPED, g.group.lower()))
    for g in ordered:
        # Worst first inside a group: what is short, then what is at the line,
        # then what nobody has decided about, then the rest.
        rank = {BELOW: 0, AT: 1, NOT_SET: 2, ABOVE: 3}
        g.lines.sort(key=lambda ln: (rank[ln.state], -ln.shortfall_units, ln.name.lower()))

    return {
        "groups": ordered,
        "to_reorder": sum(g.below_count for g in ordered),
        "no_level_recorded": sum(g.not_set_count for g in ordered),
        "items_considered": len(lines),
        "note_when_no_level": NO_LEVEL_RECORDED,
    }
