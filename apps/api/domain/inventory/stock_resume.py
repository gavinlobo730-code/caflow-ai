"""Finishing the stock effect a document did not finish (POST-A-092, the retry).

WHY THIS EXISTS

`inventory_service.apply_sale_to_inventory` and its three siblings run AFTER a document is issued and are fail-soft on purpose, so
a refused ledger row or a chart of accounts with no Inventory or Cost of Goods Sold account leaves a document that is issued and
whose stock effect is incomplete. `stock_effect` says so in words. Until this module the only advice the sentence could give was
to adjust stock by hand, or to cancel the document and enter it again.

WHAT A RETRY IS

The same four functions, called again with `resume=True`. A goods line whose stock-ledger row an earlier run already wrote is NOT
written again (a second row would take the goods out of stock twice); a row that has no journal behind it is journalled now,
together with the lines this run adds, in ONE combined journal exactly as a first run would have posted it. A document whose every
line is recorded and journalled is left alone and comes back as recorded. Nothing here prices anything: the pricing is the same
function a first run calls.

WHICH LINE BELONGS TO WHICH ROW

A movement row names its document (`source_type`, `source_id`) and its item, and not the document line that caused it. The four
functions read a document's lines in the order of the line's id, the same order on a first run and on a retry, and move them in that
order, so the first failure leaves the lines already done as a PREFIX of the lines, and per item a prefix of that item's lines.
`PriorMovements.take(item, quantity)` hands back an item's rows in the order they were written, one per line the item has on the
document: the first row to the first line, and so on. When the rows run out the line still has to be moved.

A row is handed to a line only if it is that line's: the quantity must be the line's quantity (and, on a purchase, the row's value
must be the line's cost), or the retry REFUSES in words. A document whose lines were changed after its stock was recorded (a
quantity edited, a line moved to another item) therefore never has a row attached to the wrong line.

EVERY REFUSAL COMES BEFORE THE FIRST WRITE. `rehearse` walks the owed lines over a copy of the rows and raises the first refusal, so
a retry that is going to refuse writes nothing, and "the document's stock is left as it was found" is true.

WHAT IT REFUSES, AND WHY

A stock-IN that was recorded while the item was ALREADY oversold (its stock was below nil) splits its cost between value on hand
and a Cost of Goods Sold true-up (`_compute_stock_in`), and that split is not stored on the row. Rebuilding it from the row would
be a guess about a figure that goes into the ledger. A purchase bill's or a credit note's line recorded in that position is
therefore REFUSED, in words: the document's stock is left as it is, and the sentence says to adjust stock by hand. A stock-OUT has
no such split and is never refused. (A purchase bill is refused on any such row, journalled or not, because whether its true-up
journal was ever posted cannot be told from the row either; a credit note, which posts no true-up, only on a row that has no
journal behind it.)

WHAT IT DOES NOT DO

It does not decide whether the document may be retried (a cancelled or draft document, another client's document: the route does),
and it does not lock. The route holds an in-process lock per document, which is right for one worker.
"""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

#: Which stock-in rows are refused: none (a stock-out), every one recorded against stock that was already short, or only those
#: that have no journal behind them.
REFUSE_NONE = "none"
REFUSE_ANY_SHORT = "any_short"
REFUSE_UNJOURNALLED_SHORT = "unjournalled_short"
_RULES = (REFUSE_NONE, REFUSE_ANY_SHORT, REFUSE_UNJOURNALLED_SHORT)

LINES_CHANGED_SENTENCE = (
    "its lines no longer match the stock recorded for it (a quantity or an item was changed after the stock was recorded), so which "
    "line each stock row belongs to cannot be told. Adjust stock by hand."
)
LANDED_COSTS_SENTENCE = (
    "it carries freight, insurance or duty charges and some of its stock is recorded without the journal that moves the charges, so how "
    "their share was added to each line cannot be rebuilt here. Adjust stock by hand."
)
CANNOT_RESUME_SENTENCE = (
    "a line of it was recorded while the item's stock was already below nil, and how its cost was split between the stock on hand "
    "and the cost of goods sold is not kept on the stock row, so it cannot be completed safely here. Adjust stock by hand."
)


class CannotResume(Exception):
    """Raised by `take` for a row that cannot be completed exactly. The message is the sentence a screen prints."""


class PriorMovements:
    """The stock-ledger rows one document already has, handed back one per goods line, item by item, in the order written."""

    def __init__(self, rows: list):
        self._by_item: dict = {}
        for row in rows or []:
            item = row.get("service_catalogue_id")
            if item:
                self._by_item.setdefault(str(item), []).append(row)

    @classmethod
    def load(cls, db, *, firm_id: str, client_id: str, source_type: str, source_id: str, movement_type: str) -> "PriorMovements":
        """Read the document's rows. A read that fails RAISES: a retry that could not see what is already recorded must not guess,
        because writing a line twice takes the goods out of stock twice."""
        rows = (
            db.table("inventory_stock_ledger")
            .select("id, service_catalogue_id, quantity_delta, value_delta_paise, running_qty_units, journal_entry_id, created_at")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .eq("source_type", source_type).eq("source_id", source_id).eq("movement_type", movement_type)
            .order("created_at").execute().data
        ) or []
        return cls(rows)

    def take(self, item_id: str, quantity, *, refuse: str = REFUSE_NONE, cost_paise: Optional[int] = None) -> Optional[dict]:
        """The item's next unconsumed row, or None when the line it stands for has not been moved. Raises `CannotResume` for a row that
        is not this line's (another quantity, or on a purchase another cost) and for a stock-in row the rule `refuse` says cannot be
        completed exactly."""
        if refuse not in _RULES:
            raise ValueError(f"unknown refusal rule {refuse!r}")
        queue = self._by_item.get(str(item_id))
        if not queue:
            return None
        row = queue.pop(0)
        if not _same_quantity(row, quantity):
            raise CannotResume(LINES_CHANGED_SENTENCE)
        if refuse != REFUSE_NONE and was_short_when_recorded(row):
            if refuse == REFUSE_ANY_SHORT or not row.get("journal_entry_id"):
                raise CannotResume(CANNOT_RESUME_SENTENCE)
        elif cost_paise is not None and not row.get("journal_entry_id") and not _same_value(row, cost_paise):
            # Only a row that still has to be journalled is priced from the line: one a journal already carries is skipped, and a
            # charge that landed on it (freight, duty) is no longer in the line's cost once the receipt has spent it.
            raise CannotResume(LINES_CHANGED_SENTENCE)
        return row

    def rehearse(self, owed: list, *, refuse: str = REFUSE_NONE) -> None:
        """Walk the owed lines, each `(item_id, quantity)` or `(item_id, quantity, cost_paise)`, over a COPY of the rows and raise the
        first refusal. Nothing is consumed from this object, so the real walk that follows meets the same rows."""
        copy = PriorMovements([])
        copy._by_item = {k: list(v) for k, v in self._by_item.items()}
        for entry in owed:
            copy.take(entry[0], entry[1], refuse=refuse, cost_paise=entry[2] if len(entry) > 2 else None)

    def has_unjournalled(self) -> bool:
        """True when any row has no journal behind it and a value that owes one."""
        return any(not r.get("journal_entry_id") and _paise(r) != 0 for rows in self._by_item.values() for r in rows)

    @property
    def unconsumed(self) -> int:
        """Rows no line claimed. A document never has more rows than lines, so a non-zero count means the lines changed after they
        were moved; a caller may log it."""
        return sum(len(v) for v in self._by_item.values())


def _paise(row: dict) -> int:
    try:
        return int(row.get("value_delta_paise") or 0)
    except (TypeError, ValueError):
        return 0


def _same_quantity(row: dict, quantity) -> bool:
    """The row moved this many units, in or out. A quantity that cannot be read is not the line's."""
    try:
        return abs(Decimal(str(row.get("quantity_delta")))) == abs(Decimal(str(quantity)))
    except Exception:
        return False


def _same_value(row: dict, cost_paise: int) -> bool:
    """A stock-in row recorded when the item was not short holds the line's whole cost."""
    try:
        return int(row.get("value_delta_paise")) == int(cost_paise)
    except (TypeError, ValueError):
        return False


def was_short_when_recorded(row: dict) -> bool:
    """True when the stock-in row was written while the item's quantity was already below nil: the quantity before it is the running
    quantity less the quantity it added."""
    try:
        before = Decimal(str(row.get("running_qty_units"))) - Decimal(str(row.get("quantity_delta")))
    except Exception:
        # A row whose quantities cannot be read is not one to complete by arithmetic.
        return True
    return before < 0
