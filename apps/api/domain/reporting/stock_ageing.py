"""How long has the stock ON HAND been held (INV-04).

WHAT WAS MISSING, AND WHAT WAS NOT

    The slow/non-moving half of INV-04 is built: the inventory screen renders
    Last Moved and Days Idle off migration 363's `stock_position_as_at`, so a
    CA can already see which ITEMS have not moved. That answers a question
    about the ITEM.

    Ageing proper is a question about the UNITS. An item selling steadily has a
    recent last-movement date and may still be carrying forty units bought
    three years ago behind the ones that keep turning over — and those forty
    are the obsolescence AS-2 paragraph 24 makes the CA write down to net
    realisable value. The register offers a write-down endpoint
    (`routers/inventory.py`) and gave the CA nothing to decide it on.

    This is also the quantitative half of a stock audit: "show me everything
    over a year old" is among the first things asked, and Tally has had Stock
    Ageing Analysis as a standard report for decades.

AGEING IS FIFO, WHATEVER THE CLIENT'S COST FORMULA IS, AND THAT IS NOT A
CONTRADICTION

    `clients.inventory_costing_method` (migration 394) decides how cost is
    ASSIGNED to what goes out — AS-2 paragraph 14 permits FIFO or weighted
    average. This report does not assign cost. It asks a physical question:
    of the units sitting in the godown today, when did each arrive?

    Goods leave a godown oldest-first whether or not the books cost them that
    way. A weighted-average client does not sell its newest stock first; it
    just values the issue at a blended figure. So the consumption assumption
    here is FIFO for every client, and `domain/inventory/costing.py` is
    untouched — a test asserts this module never reads the costing policy and
    that module never reads these buckets.

WHY THE VALUE IS PRO-RATED AND IS NOT THE LAYER'S OWN COST

    It would be easy, having replayed the layers, to report each layer's own
    `value_delta_paise`. It would also be wrong for most clients: under the
    weighted average the value that LEFT was the blended cost, so the FIFO
    layers' surviving costs do not sum to the item's book value — and a stock
    ageing report whose total disagrees with the Inventories line is worse than
    no report, because somebody will foot it.

    So the quantity buckets are the FIFO answer and the VALUE in each is the
    item's own book value (Σ `value_delta_paise`, which ties to the Inventory
    control account by construction — see migration 363) split across the
    buckets in proportion to quantity, largest remainder so the parts sum to
    the whole exactly. Every answer says so. It is the figure a provision is
    computed on — "62% of these units are over a year old, so ₹X of the
    carrying amount is" — and it is not a claim about what those units cost.

THE BANDS ARE A CONVENTION AND THE MODULE SAYS SO

    Schedule III prescribes ageing for trade receivables and trade payables
    (MCA G.S.R. 207(E) of 24-03-2021, in `domain/reporting/ageing.py`) and
    prescribes NOTHING for inventory. AS-2 requires the net-realisable-value
    assessment and sets no bands for it. So these six are a reporting
    convention chosen to answer both questions the report is opened for — the
    working-capital one at the short end and the obsolescence one at the long —
    and not a rule anybody may cite.

WHAT IT REFUSES

    * **No provision is computed and no percentage is applied.** A sliding
      scale — 25% at a year, 50% at two — is a policy some firms run and no
      standard states, and AS-2 paragraph 21 makes NRV an estimate of selling
      price less costs to complete and sell, which is a fact about the market
      that no ledger holds. The report gives the CA the quantities; the
      write-down stays theirs, through the endpoint that already exists.
    * **Nothing is bucketed by godown or batch.** Both are on the ledger since
      migration 398 and adding either multiplies the rows by a dimension the
      obsolescence question does not turn on. `batches.BUCKETS` already ages by
      EXPIRY, which is the other question and a different one.
    * **A negative position is reported as itself, never as empty buckets.** An
      oversold item has no units on hand to age, and showing six zeroes beside
      a negative quantity reads as "nothing old here".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Optional, Sequence

#: The bands, youngest first. UPPER BOUND IN DAYS, `None` for the open end.
#: Each band is "up to and including" its bound, so a unit received exactly 30
#: days ago is in the first band — the boundary is stated rather than left to
#: whichever comparison somebody wrote, because the same figure appearing in
#: two adjacent columns on two screens is the defect this pins.
BANDS: tuple[tuple[str, Optional[int]], ...] = (
    ("d0_30", 30),
    ("d31_60", 60),
    ("d61_90", 90),
    ("d91_180", 180),
    ("d181_365", 365),
    ("d365_plus", None),
)

BAND_KEYS = tuple(k for k, _ in BANDS)

BAND_LABELS = {
    "d0_30": "0–30 days",
    "d31_60": "31–60 days",
    "d61_90": "61–90 days",
    "d91_180": "91–180 days",
    "d181_365": "181–365 days",
    "d365_plus": "Over 365 days",
}

#: Said on every answer. Schedule III prescribes bands for trade receivables
#: and payables and none for inventory, and AS-2 sets none either.
BANDS_ARE_A_CONVENTION = (
    "These bands are a reporting convention, not a prescribed disclosure. "
    "Schedule III's ageing schedules (MCA G.S.R. 207(E) of 24-03-2021) cover "
    "trade receivables and trade payables only, and AS-2 requires the "
    "net-realisable-value assessment without setting bands for it."
)

VALUE_IS_PRO_RATED = (
    "Quantities are aged first-in-first-out. The value in each band is the "
    "item's own carrying amount split in proportion to quantity — not the cost "
    "of the units in that band. Under the weighted average the cost that left "
    "was a blended figure, so layer costs would not sum to the carrying amount "
    "and the report would not foot to the Inventories line."
)

AGEING_IS_FIFO_WHATEVER_THE_POLICY = (
    "Ageing assumes goods leave oldest-first, for every client, whatever cost "
    "formula their books use. That is a physical assumption about the godown "
    "and not a cost assignment: AS-2 paragraph 14's choice governs what an "
    "issue is valued at, not which carton was carried out."
)

NO_PROVISION_IS_COMPUTED = (
    "No provision or write-down percentage is applied. AS-2 paragraph 21 makes "
    "net realisable value an estimate of selling price less the costs to "
    "complete and sell — a fact about the market that no ledger holds — so the "
    "quantities are reported and the write-down stays the CA's."
)


def band_for_age(age_days: int) -> str:
    """Which band a unit held `age_days` days belongs in.

    The ONE place the boundary is decided, so the SQL twin, the Python twin and
    the screen cannot disagree about where 30 days falls.
    """
    for key, upper in BANDS:
        if upper is None or age_days <= upper:
            return key
    return BAND_KEYS[-1]


@dataclass(frozen=True)
class Movement:
    """One `inventory_stock_ledger` row, as this report needs it."""
    movement_date: date
    quantity_delta: Decimal
    value_delta_paise: int
    created_at: str = ""
    row_id: str = ""


@dataclass
class ItemAgeing:
    service_catalogue_id: str
    name: str
    unit: str = ""
    qty_units: Decimal = Decimal(0)
    value_paise: int = 0
    band_qty: dict = field(default_factory=dict)
    band_value_paise: dict = field(default_factory=dict)
    oldest_holding_date: Optional[date] = None
    #: True where Σ quantity_delta is at or below nil — nothing to age, and the
    #: bands are empty for a REASON rather than because the stock is new.
    nothing_on_hand: bool = False

    def to_dict(self) -> dict:
        return {
            "service_catalogue_id": self.service_catalogue_id,
            "name": self.name,
            "unit": self.unit,
            "qty_units": str(self.qty_units),
            "value_paise": self.value_paise,
            "band_qty": {k: str(self.band_qty.get(k, Decimal(0)))
                         for k in BAND_KEYS},
            "band_value_paise": {k: int(self.band_value_paise.get(k, 0))
                                 for k in BAND_KEYS},
            "oldest_holding_date": (self.oldest_holding_date.isoformat()
                                    if self.oldest_holding_date else None),
            "nothing_on_hand": self.nothing_on_hand,
        }


def _remaining_layers(movements: Sequence[Movement]):
    """The FIFO layers still on hand, oldest first, as (date, qty, value).

    THE CONSUMPTION IS AGGREGATE, NOT STEP BY STEP, and that is what makes it
    order-independent in the way migration 363 relies on. Let `T` be the total
    quantity that went OUT over the whole history and `cum` the cumulative
    quantity IN up to and including a layer: what survives of that layer is
    `min(layer_qty, max(0, cum - T))`. A layer entirely before `T` is gone, the
    one straddling it is part-consumed, and everything after it is untouched.

    Walking the movements one at a time and decrementing gives the same answer
    whenever the position is non-negative, and DIFFERS only in the oversold
    case — where the step-by-step walk has to invent a rule for what a later
    receipt clears first. The aggregate form has no such case: the position is
    what the deltas sum to, and if that is nil or less there is nothing on hand.
    """
    ins = sorted((m for m in movements if m.quantity_delta > 0),
                 key=lambda m: (m.movement_date, m.created_at, m.row_id))
    total_out = -sum((m.quantity_delta for m in movements
                      if m.quantity_delta < 0), Decimal(0))
    out = []
    cum = Decimal(0)
    for m in ins:
        cum += m.quantity_delta
        survives = min(m.quantity_delta, max(Decimal(0), cum - total_out))
        if survives > 0:
            out.append((m.movement_date, survives, m.value_delta_paise))
    return out


def _split_pro_rata(total_paise: int, weights: Sequence[Decimal]) -> list[int]:
    """`total_paise` split across `weights`, largest remainder, summing exactly.

    The same discipline `domain/gst/discount.py` and
    `domain/inventory/landed_cost.py` use, and for the same reason: the parts
    have to add back to the whole or the report does not foot to the figure it
    was derived from.
    """
    n = len(weights)
    if n == 0:
        return []
    total_weight = sum(weights, Decimal(0))
    if total_weight <= 0:
        return [0] * n
    # A NEGATIVE carrying amount is possible — an oversell can drive the value
    # below nil — and the largest-remainder walk is written on the magnitude so
    # the sign cannot flip a share.
    sign = -1 if total_paise < 0 else 1
    magnitude = abs(total_paise)
    exact = [Decimal(magnitude) * w / total_weight for w in weights]
    floors = [int(e) for e in exact]
    short = magnitude - sum(floors)
    order = sorted(range(n), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in order[:short]:
        floors[i] += 1
    return [sign * f for f in floors]


def compute(items, as_of: date) -> dict:
    """The ageing for a whole register.

    `items` is an iterable of (meta, movements) where meta carries
    `service_catalogue_id`, `name` and `unit`. Nothing is fetched here — this
    module has no database handle, the same shape as
    `domain/reporting/fixed_asset_movement.py`.
    """
    rows: list[ItemAgeing] = []
    for meta, movements in items:
        rows.append(_one_item(meta, list(movements), as_of))
    rows.sort(key=lambda r: (r.name.lower(), r.service_catalogue_id))

    totals_qty = {k: Decimal(0) for k in BAND_KEYS}
    totals_value = {k: 0 for k in BAND_KEYS}
    for r in rows:
        for k in BAND_KEYS:
            totals_qty[k] += r.band_qty.get(k, Decimal(0))
            totals_value[k] += int(r.band_value_paise.get(k, 0))

    return {
        "as_of": as_of.isoformat(),
        "bands": list(BAND_KEYS),
        "band_labels": dict(BAND_LABELS),
        "items": [r.to_dict() for r in rows],
        "total_qty_by_band": {k: str(totals_qty[k]) for k in BAND_KEYS},
        "total_value_by_band": {k: totals_value[k] for k in BAND_KEYS},
        # Ties to the Inventory control account, by construction: it is the
        # same Σ value_delta_paise migration 363 reports.
        "total_value_paise": sum(r.value_paise for r in rows),
        "total_items": len(rows),
        "notes": [
            BANDS_ARE_A_CONVENTION,
            AGEING_IS_FIFO_WHATEVER_THE_POLICY,
            VALUE_IS_PRO_RATED,
            NO_PROVISION_IS_COMPUTED,
        ],
    }


def _one_item(meta, movements: list[Movement], as_of: date) -> ItemAgeing:
    row = ItemAgeing(
        service_catalogue_id=str(meta.get("service_catalogue_id") or ""),
        name=str(meta.get("name") or "(deleted item)"),
        unit=str(meta.get("unit") or ""),
        band_qty={k: Decimal(0) for k in BAND_KEYS},
        band_value_paise={k: 0 for k in BAND_KEYS},
    )
    row.qty_units = sum((m.quantity_delta for m in movements), Decimal(0))
    row.value_paise = sum(int(m.value_delta_paise) for m in movements)

    if row.qty_units <= 0:
        # NOTHING TO AGE, and the flag says which of the two nils this is.
        # Six zeroes beside a negative quantity read as "no old stock here",
        # which is the opposite of what an oversold item is telling the CA.
        row.nothing_on_hand = True
        return row

    layers = _remaining_layers(movements)
    if layers:
        row.oldest_holding_date = layers[0][0]

    keys, weights = [], []
    for held_on, qty, _value in layers:
        band = band_for_age((as_of - held_on).days)
        row.band_qty[band] += qty
        keys.append(band)
        weights.append(qty)

    # The value follows the QUANTITY, and is split once over the bands rather
    # than per layer — splitting per layer and summing would round six times
    # where it should round once.
    band_weights = [row.band_qty[k] for k in BAND_KEYS]
    shares = _split_pro_rata(row.value_paise, band_weights)
    for k, share in zip(BAND_KEYS, shares):
        row.band_value_paise[k] = share
    return row


def ageing(rows, as_of, names: Optional[dict] = None) -> dict:
    """The whole-register answer from raw `inventory_stock_ledger` rows.

    THE SAME SHAPE `domain/reporting/stock_position.position` TAKES, on purpose:
    both are read from the same table by the same service, and a second row
    shape would be a second place to get `quantity_delta`'s string-vs-Decimal
    round trip wrong. PostgREST renders NUMERIC(10,3) as a STRING and a bigint
    as a string too, so everything goes through `Decimal(str(...))` and nothing
    here ever sees a float — `0.29 * 100` is 28.999999999999996 and this report
    has to foot.

    `names` is `{item_id: {"name": ..., "unit": ...}}`. An item the caller
    could not name is "(deleted item)" rather than dropped: a register that
    silently omits rows cannot be tied to the Inventory control account by
    somebody who does not know which rows it dropped — migration 363's rule.
    """
    as_of_date = as_of if isinstance(as_of, date) else date.fromisoformat(str(as_of))
    names = names or {}
    by_item: dict = {}
    for i, r in enumerate(rows):
        item = str(r.get("service_catalogue_id") or "")
        if not item:
            continue
        when = date.fromisoformat(str(r.get("movement_date")))
        # AS AT A DATE, and the filter belongs HERE rather than on the caller.
        # The SQL twin applies it in its own WHERE clause, so a Python half
        # that trusted the caller would answer differently for the one caller
        # that forgot — and an item with no movements on or before the date
        # must not appear at all, which only a pre-grouping filter gives.
        if when > as_of_date:
            continue
        by_item.setdefault(item, []).append(Movement(
            movement_date=when,
            quantity_delta=Decimal(str(r.get("quantity_delta") or 0)),
            value_delta_paise=int(Decimal(str(r.get("value_delta_paise") or 0))),
            created_at=str(r.get("created_at") or ""),
            # The THIRD sort key. It is DETERMINISM rather than correctness,
            # and the difference is worth stating because the obvious claim is
            # wrong: two receipts sharing a movement_date share a BAND by
            # construction — the band is a function of that date alone — so
            # whichever of them the consumption eats first, the band
            # quantities and the pro-rated value come out identical. Nothing
            # here can change a figure.
            #
            # What it buys is that the answer does not depend on the order the
            # caller fetched the rows in, and that the SQL twin (which breaks
            # the same tie on `id`) walks the same layers, so a future change
            # that DOES make the layer identity matter cannot quietly make the
            # two halves disagree. Falls back to the row's position.
            row_id=str(r.get("id") or i),
        ))
    items = []
    for item, movements in by_item.items():
        meta = dict(names.get(item) or {})
        meta["service_catalogue_id"] = item
        items.append((meta, movements))
    return compute(items, as_of_date)
