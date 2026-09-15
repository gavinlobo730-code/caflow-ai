"""Which cost formula prices a stock issue — AS-2 paragraph 14, and AS-5's
consequence for changing it (INV-02).

WHY THIS EXISTS
    `domain/inventory_service.py` priced every issue at the MOVING AVERAGE and
    had no other answer. AS-2 paragraph 14 permits the cost of inventories to
    be assigned by using the **first-in, first-out (FIFO)** or **weighted
    average** cost formula, and a practice's clients use both: FIFO is
    ordinary in trading and in anything with a shelf life, and is what a
    client migrating from Tally (whose default is FIFO for many stock groups)
    arrives with.

    A client whose books are kept on FIFO and whose software can only do
    weighted average has a closing stock figure — and therefore a PROFIT —
    that its own accounting policy note does not describe.

THREE RULES, AND THE SECOND IS THE ONE THAT BITES

    1. THE FORMULA IS A POLICY, NOT A PER-MOVEMENT CHOICE. AS-2 paragraph 16:
       the same cost formula shall be used for all inventories having a
       similar nature and use to the enterprise. So it lives on the CLIENT and
       not on a receipt, and no caller may pass one.

    2. CHANGING IT IS A CHANGE IN ACCOUNTING POLICY. AS-5 paragraph 29 allows
       one only if required by statute, by an accounting standard, or if the
       change would result in a more appropriate presentation — and paragraph
       32 requires the change and its EFFECT to be disclosed. So a switch is
       PROSPECTIVE from a stated date and the ledger records which formula
       priced each row; re-costing history silently would move last year's
       closing stock, and with it last year's profit, on a return already
       filed. `switch_refusal` is where that is decided.

    3. STANDARD COST IS REFUSED AND NAMED. AS-2 paragraph 17 allows it "for
       convenience if the results approximate the actual cost", taking into
       account normal levels of consumption, and requires the standards to be
       regularly reviewed and revised. Both limbs are judgements, and the
       method needs a variance account and a periodic revision to work at all.
       It is named rather than half-built.

WHAT IS NOT DECIDED HERE
    Nothing about the ledger's shape. A FIFO issue produces the same
    `value_delta_paise` the moving-average one does — that figure is what the
    COGS journal posts and what ties the stock ledger to the Inventory control
    account — so the two formulas differ only in the NUMBER, never in the
    mechanism. That is what lets one posting path serve both.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Optional

#: AS-2 paragraph 14's two formulas, and nothing else.
MOVING_AVERAGE = "moving_average"
FIFO = "fifo"
METHODS = (MOVING_AVERAGE, FIFO)

METHOD_LABELS = {
    MOVING_AVERAGE: "Weighted average (AS-2 paragraph 14)",
    FIFO: "First-in, first-out (AS-2 paragraph 14)",
}

#: What a client with nothing recorded is on. NOT a default in the "we had to
#: pick something" sense: every client's books in this product HAVE been kept
#: on the moving average, because it was the only formula there was. NULL
#: records that nobody has CHOSEN, and the answer is a fact about how the
#: books were actually kept.
METHOD_WHEN_UNRECORDED = MOVING_AVERAGE
UNRECORDED_MEANS = (
    "No cost formula is recorded for this client, and the answer is not a "
    "guess: every issue in these books was priced at the weighted average, "
    "because it was the only formula the product had. Recording one is "
    "therefore confirming what has been done, or changing it — and a change "
    "is AS-5 paragraph 29's change in accounting policy."
)

STANDARD_COST_REFUSED = (
    "Standard cost is not offered. AS-2 paragraph 17 allows it 'for "
    "convenience if the results approximate the actual cost', taking normal "
    "levels of consumption into account, and requires the standards to be "
    "regularly reviewed and revised in the light of current conditions. Both "
    "limbs are judgements no ledger holds, and the method needs a variance "
    "account and a revision cycle to mean anything — so it is named here "
    "rather than half-built."
)

AS5_DISCLOSURE = (
    "AS-5 paragraph 32: a change in an accounting policy that has a material "
    "effect shall be disclosed, with the amount by which any item in the "
    "financial statements is affected. `inventory_stock_ledger.costing_method` "
    "records which formula priced each movement, so the change and the period "
    "it took effect from are derivable from the ledger rather than remembered."
)


def method_for(recorded: Optional[str]) -> str:
    """The formula in force, from what the client recorded."""
    value = (recorded or "").strip().lower()
    return value if value in METHODS else METHOD_WHEN_UNRECORDED


@dataclass(frozen=True)
class CostingPolicy:
    """One client's cost formula, carried WITH the client it belongs to.

    The posting paths resolve this ONCE per document and hand it down to each
    line, because re-reading `clients` per line would be one
    Singapore-to-Mumbai round trip per line of an invoice. Carrying the
    `client_id` is what makes that safe: `record_stock_out` refuses a policy
    whose client is not the movement's client, so a caller cannot pass another
    client's formula — or an arbitrary string — however the plumbing is later
    rearranged. AS-2 paragraph 16 makes the formula a property of the
    enterprise's inventories, so a per-movement choice is not a thing this
    engine will accept.
    """
    client_id: str
    method: str

    def __post_init__(self) -> None:
        if self.method not in METHODS:
            raise ValueError(
                f"{self.method!r} is not a cost formula AS-2 paragraph 14 "
                f"permits. " + STANDARD_COST_REFUSED)

    @property
    def label(self) -> str:
        return METHOD_LABELS[self.method]

    @property
    def is_fifo(self) -> bool:
        return self.method == FIFO


def policy_for(client_id: str, recorded: Optional[str]) -> CostingPolicy:
    """The policy in force for a client, from the column as stored."""
    return CostingPolicy(client_id=str(client_id), method=method_for(recorded))


def switch_refusal(*, current: Optional[str], wanted: str,
                   effective_from: Optional[str],
                   movement_on_or_after: Optional[str] = None) -> Optional[str]:
    """Why this change of cost formula cannot be made as asked, or None.

    THE SWITCH IS PROSPECTIVE AND THE DATE IS REQUIRED. Re-costing history
    would move a closing stock figure that is already in a filed return and a
    signed balance sheet, and AS-5 paragraph 32 asks for the EFFECT of a
    change to be disclosed — which is not a thing software may compute by
    quietly restating the past.
    """
    if wanted not in METHODS:
        return (f"{wanted!r} is not a cost formula AS-2 paragraph 14 permits. "
                f"The two are: " + ", ".join(METHOD_LABELS[m] for m in METHODS)
                + ". " + STANDARD_COST_REFUSED)
    # A client with NOTHING recorded may record the weighted average: that is
    # confirming in writing what the books have always been kept on, not a
    # change, and it is how a CA says "we have considered this". Only a client
    # already on that formula is told there is nothing to do.
    if current and method_for(current) == wanted:
        return f"This client is already on {METHOD_LABELS[wanted]}."
    if not effective_from:
        return ("A change of cost formula takes effect from a DATE and is not "
                "retrospective. Say which date it applies from — AS-5 "
                "paragraph 29 permits the change and paragraph 32 asks for its "
                "effect to be disclosed, and re-costing movements already in a "
                "filed return would move a closing stock figure somebody has "
                "signed.")
    if movement_on_or_after:
        # A movement already recorded on or after that date was PRICED on the
        # formula in force when it was recorded, and nothing is ever
        # re-costed. Letting the change take effect behind it would leave the
        # ledger's own stamps contradicting the policy the client is said to
        # be on — and the first person to notice would be an auditor
        # reconciling the closing stock.
        return ("Stock has already moved on or after "
                f"{effective_from} (the earliest is {movement_on_or_after}). "
                "Those movements were priced on the formula in force when "
                "they were recorded and nothing is re-costed, so the change "
                "has to take effect from a date after the last recorded "
                "movement — the start of the next period is the usual "
                "answer. " + AS5_DISCLOSURE)
    return None


# ── FIFO ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Layer:
    """One receipt still (partly) on hand, and what that part is worth.

    A LAYER CARRIES ITS VALUE, NOT A UNIT COST, and that is the same decision
    `_compute_stock_in` makes when it blends the average from the exact total
    rather than from a rounded per-unit figure. Three units costing ₹100 have
    a unit cost of 3,333 paise and a value of 10,000 — and `3 × 3,333` is
    9,999. Carrying the unit cost would put that one paise between the layers
    and the ledger's own running value on every receipt whose cost does not
    divide by its quantity, which is most of them, and the difference would be
    indistinguishable from the real one a cancellation reversal leaves.
    """
    quantity: Decimal
    value_paise: int

    @property
    def unit_cost_paise(self) -> int:
        if self.quantity <= 0:
            return 0
        return _round_paise(Decimal(self.value_paise) / self.quantity)


@dataclass
class Issue:
    """What a FIFO issue costs, and what is left behind."""
    value_paise: int = 0
    #: The layers after the issue, oldest first.
    remaining: tuple = ()
    #: Units the layers could not cover — an oversell. Priced at ZERO, exactly
    #: as the moving-average path does, so the two agree about the one thing
    #: that is not a cost: stock that was never bought.
    uncovered_quantity: Decimal = Decimal(0)

    def as_dict(self) -> dict:
        return {
            "value_paise": self.value_paise,
            "remaining": [{"quantity": str(l.quantity),
                           "value_paise": l.value_paise,
                           "unit_cost_paise": l.unit_cost_paise}
                          for l in self.remaining],
            "uncovered_quantity": str(self.uncovered_quantity),
        }


@dataclass(frozen=True)
class Position:
    """What a replay of an item's movements leaves behind.

    `deficit` is the OVERSOLD quantity — units issued that no receipt had yet
    covered. It is not a layer and has no cost: `domain/inventory_service`'s
    force-close invariant pairs a quantity at or below zero with a value of
    exactly zero, and the next receipt absorbs the deficit before any of it
    becomes stock on hand. Replaying without tracking it would turn that
    receipt into a layer of its full quantity and value units that were
    already sold.
    """
    layers: tuple = ()
    deficit: Decimal = Decimal(0)

    @property
    def quantity(self) -> Decimal:
        return quantity_of(self.layers) - self.deficit

    @property
    def value_paise(self) -> int:
        return value_of(self.layers)


def layers_from_movements(movements: Iterable[dict], *,
                          opening_deficit: Decimal = Decimal(0)) -> Position:
    """The receipts still on hand, oldest first, replayed from the ledger.

    DERIVED, NEVER STORED — migration 278's reasoning applied to a cost layer.
    A stored layer table would be a second record of the same movements, and
    it would be wrong the moment one is reversed; the ledger already holds
    every movement with its own value, which is all FIFO needs.

    `movements` are that item's rows in the order they were RECORDED, which is
    the order `_last_ledger_row` chains the running totals in and the order
    this must replay in: a backdated bill entered after a sale cannot
    retrospectively become the layer that sale consumed, because the sale has
    already been priced and posted.

    A RECEIPT'S LAYER IS WORTH ITS OWN `value_delta_paise`, which is the
    figure the ledger added to the running value — so the layers tie to the
    books exactly, receipt by receipt, with no residue to explain away. That
    delta is ALREADY net of any oversold deficit the receipt cleared
    (`_compute_stock_in`'s absorb split): the covering portion's cost is the
    true-up for units already gone, not value on hand. So the quantity is
    reduced by the same covered units here, or the layer would hold the right
    value over too many units and every later issue would be under-costed.
    """
    layers: list = []
    deficit = Decimal(opening_deficit)
    for m in movements:
        qty = Decimal(str(m.get("quantity_delta") or 0))
        if qty > 0:
            if deficit > 0:
                covered = min(qty, deficit)
                deficit -= covered
                qty -= covered
            if qty > 0:
                layers.append(Layer(quantity=qty,
                                    value_paise=int(m.get("value_delta_paise") or 0)))
        elif qty < 0:
            issue = consume(layers, -qty)
            layers = list(issue.remaining)
            deficit += issue.uncovered_quantity
        else:
            # A movement that changes VALUE and not quantity is a write-down
            # to net realisable value (`_compute_nrv_writedown`). AS-2
            # paragraph 5 carries inventories at the lower of cost and net
            # realisable value, and the written-down amount is what the
            # remaining units are carried at from then on — so every layer is
            # re-costed to the row's own new running value. Replaying it as
            # "no change" would price the next issue at a cost the books wrote
            # off, and leave the layers disagreeing with the ledger by exactly
            # the write-down.
            if layers and int(m.get("value_delta_paise") or 0) != 0:
                layers = list(rebase(layers, int(m.get("running_value_paise") or 0)))
    return Position(layers=tuple(layers), deficit=deficit)


def rebase(layers: Iterable, to_value_paise: int) -> tuple:
    """Re-cost the layers so they are worth exactly `to_value_paise`.

    WHEN THIS IS NEEDED, AND WHY IT IS NOT ALWAYS A BUG. The ledger's chained
    `running_value_paise` is what the Inventory control account holds and what
    `domain/reporting/stock_position.py` sums, so it is the authority on the
    VALUE on hand; the layers are the authority on WHICH units are on hand.
    They agree for every receipt and every issue, because a layer carries the
    ledger's own `value_delta_paise`. They part company on a CANCELLATION
    REVERSAL — `record_stock_out_at_value` deliberately removes the value the
    original movement ADDED, because the journal side reverses that entry at
    its original value, and that is not a first-in first-out concept at all:
    it can take out a newer layer's cost while the quantity comes off the
    oldest. A write-down to net realisable value uses this too, and there it
    is the ordinary course rather than a disagreement.

    Where they differ the books win, and the remainder is carried at one
    weighted figure — which is what the weighted-average formula would have
    said about the same units, and is the only answer that cannot leave the
    stock ledger and the Inventory account disagreeing.

    LARGEST REMAINDER, so the parts sum to the whole EXACTLY — the same reason
    `domain/gst/discount.py` splits a document-level discount that way. A
    per-layer rounding would reintroduce the very residue this exists to
    remove.
    """
    layers = tuple(layers)
    total_qty = quantity_of(layers)
    if total_qty <= 0:
        return ()
    shares, remainders = [], []
    for i, l in enumerate(layers):
        exact = Decimal(to_value_paise) * l.quantity / total_qty
        whole = int(exact)          # truncates toward zero; values are >= 0
        shares.append(whole)
        remainders.append((exact - whole, i))
    residue = to_value_paise - sum(shares)
    for _, i in sorted(remainders, key=lambda t: (-t[0], t[1]))[:max(0, residue)]:
        shares[i] += 1
    return tuple(Layer(quantity=l.quantity, value_paise=shares[i])
                 for i, l in enumerate(layers))


def consume(layers: Iterable, quantity: Decimal) -> Issue:
    """Take `quantity` off the oldest layers first, and say what it cost.

    A WHOLE LAYER IS TAKEN AT ITS WHOLE VALUE and a part layer is split by
    quantity, with the remainder keeping exactly what is left — so what goes
    out plus what stays behind is what was there, to the paise, however many
    times an issue splits a layer. That is the property the ledger's
    force-close invariant depends on.

    An issue larger than everything on hand is NOT an error: the
    moving-average path records an oversell at zero cost and self-corrects
    when stock arrives, and FIFO must behave the same or the two formulas
    would disagree about a case that has nothing to do with either of them.
    """
    if quantity <= 0:
        raise ValueError("An issue must be of a positive quantity.")
    left = Decimal(quantity)
    value = 0
    out: list = []
    for layer in layers:
        if left <= 0:
            out.append(layer)
            continue
        if layer.quantity <= left:
            value += layer.value_paise
            left -= layer.quantity
            continue
        part = _round_paise(Decimal(layer.value_paise) * left / layer.quantity)
        part = min(part, layer.value_paise)
        value += part
        out.append(Layer(quantity=layer.quantity - left,
                         value_paise=layer.value_paise - part))
        left = Decimal(0)
    return Issue(value_paise=value, remaining=tuple(out),
                 uncovered_quantity=max(Decimal(0), left))


def value_of(layers: Iterable) -> int:
    """What the layers are worth — the FIFO closing stock figure."""
    return sum(l.value_paise for l in layers)


def quantity_of(layers: Iterable) -> Decimal:
    return sum((l.quantity for l in layers), Decimal(0))


def _round_paise(value) -> int:
    """Money is integer paise. `Decimal(str(...))`, never a float."""
    from decimal import ROUND_HALF_UP
    return int(Decimal(str(value)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
