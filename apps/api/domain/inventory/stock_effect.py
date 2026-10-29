"""What a document did to stock, and the sentence when it did not do all of it (POST-A-092, the stock half).

WHY THIS EXISTS

A sales invoice, a purchase bill, a credit note and a purchase debit note move stock AFTER the document itself is
committed (`inventory_service.apply_sale_to_inventory` and its three siblings). They are fail-soft on purpose: a
missing Inventory or Cost of Goods Sold account, or a refused ledger row, must never un-issue a document that is already
in the books and the return. The failure went to Sentry and nowhere else, so the document read as complete while the
stock ledger and the Inventory control account lacked it. Nothing on the document, and nothing in the response that
issued it, said so.

This module is the answer the four functions now give. It holds NO accounting: the functions record what they did (how
many goods lines they meant to move, how many they moved, whether the journal behind the movements was posted) and this
turns that into one fact the routes put on the response and the screens print. The sentence is written HERE, once, so
four screens cannot word one failure four ways.

THE THREE STATES, AND WHY THEY ARE NOT ONE

    recorded            every goods line moved and the journal that goes with it was posted (or none was owed: a
                        movement with no cost basis yet posts nothing).
    not recorded        a goods line did not move. The stock ledger and the Inventory account do not include it.
    journal not posted  the lines moved and the journal did not. The stock ledger is AHEAD of the general ledger, which
                        is the shape `reconciliation_service.check_missing_cogs_journals` finds at night; saying it at
                        issue time lets the CA act while they still remember the document.

A document with NO goods line is not a "recorded" one, it is a document stock is not involved in, and `as_dict()` returns
None for it: an absent answer and a good answer must not look alike on the wire.

WHAT THIS DOES NOT DO

It does not retry, and it does not change what the four functions write. A partly moved document (line 1 written, line 2
refused) still leaves the stock ledger ahead of the general ledger by line 1: the COGS journal is posted from a total that
is only reached when every line moved. That is recorded in the design record, and the nightly check still finds it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

JOURNAL_NOT_OWED = "not_owed"
JOURNAL_POSTED = "posted"
JOURNAL_NOT_POSTED = "not_posted"
JOURNAL_STATES = (JOURNAL_NOT_OWED, JOURNAL_POSTED, JOURNAL_NOT_POSTED)

#: (the document as a person names it, what the CA did to it, what was meant to happen to stock). The same four
#: documents `inventory_service.apply_*` serve; a purchase credit note and a sales debit note never move stock.
DOCUMENTS = {
    "sales_invoice": ("sales invoice", "issued", "the goods it sold were not taken out of stock"),
    "purchase_bill": ("purchase bill", "received", "the goods it bought were not added to stock"),
    "credit_note": ("credit note", "issued", "the goods it returns were not added back to stock"),
    "debit_note": ("debit note", "issued", "the goods it returns to the supplier were not taken out of stock"),
}

_CHECK = ("Adjust stock by hand, or cancel the document and enter it again once the cause is fixed. Until then the stock "
          "report and the Inventory account do not agree with this document.")


@dataclass
class StockEffect:
    """What one document did to stock. `kind` is a key of DOCUMENTS."""
    kind: str
    #: Goods lines the document carries for this client's own stock-tracked item with a quantity: the lines it meant
    #: to move. Counted as the loop reaches them, so after a failure it is the lines SEEN, not the lines the document has.
    goods_lines: int = 0
    #: Of those, the lines whose stock-ledger row was written.
    moved_lines: int = 0
    journal: str = JOURNAL_NOT_OWED
    #: Set when anything raised before the work was done. The words are for the log, never for a screen.
    stopped_by: Optional[str] = None
    #: The document's own number, so a sentence in a bulk run names the document it is about.
    reference: Optional[str] = None

    def __post_init__(self) -> None:
        if self.kind not in DOCUMENTS:
            raise ValueError(f"unknown document kind {self.kind!r}")
        if self.journal not in JOURNAL_STATES:
            raise ValueError(f"unknown journal state {self.journal!r}")

    def note_journal(self, posted: bool) -> None:
        """Record what a journal call returned. A journal that was not posted stays not posted whatever a later one does."""
        if not posted:
            self.journal = JOURNAL_NOT_POSTED
        elif self.journal == JOURNAL_NOT_OWED:
            self.journal = JOURNAL_POSTED

    @property
    def involves_stock(self) -> bool:
        """False for a document with no goods line, which stock has nothing to say about."""
        return self.goods_lines > 0 or self.stopped_by is not None

    @property
    def lines_not_moved(self) -> bool:
        """A goods line was reached and did not move, or the call stopped before it could say how many there were."""
        return self.moved_lines < self.goods_lines or (self.stopped_by is not None and self.goods_lines == 0)

    @property
    def recorded(self) -> bool:
        return self.stopped_by is None and not self.lines_not_moved and self.journal != JOURNAL_NOT_POSTED

    def problem(self) -> Optional[str]:
        """The sentence a screen prints, or None when there is nothing to say."""
        if self.recorded:
            return None
        noun, verb, meant = DOCUMENTS[self.kind]
        ref = str(self.reference).strip() if self.reference else ""
        head = f"{noun.capitalize()} {ref} was {verb}, but " if ref else f"This {noun} was {verb}, but "
        if self.lines_not_moved:
            if self.moved_lines == 0:
                return f"{head}{meant}. {_CHECK}"
            return (f"{head}stock was recorded for only {self.moved_lines} of its goods lines before an error "
                    f"stopped the rest, and the journal that moves their value between Inventory and the cost accounts "
                    f"was not posted. {_CHECK}")
        if self.journal == JOURNAL_NOT_POSTED:
            return (f"{head}the journal that moves the value of its goods between Inventory and the cost accounts was "
                    f"not posted, so the stock ledger is ahead of the general ledger by this document. Check that the "
                    f"chart of accounts has an Inventory account and a Cost of Goods Sold account. {_CHECK}")
        return (f"{head}an error stopped part of its stock effect from being recorded, so it may be incomplete. {_CHECK}")

    def as_dict(self) -> Optional[dict]:
        """The answer on the wire, or None when stock is not involved. `problem` is None exactly when `recorded`."""
        if not self.involves_stock:
            return None
        return {
            "recorded": self.recorded,
            "goods_lines": self.goods_lines,
            "moved_lines": self.moved_lines,
            "journal": self.journal,
            "reference": self.reference,
            "problem": self.problem(),
        }


def failed(kind: str, reason: str, reference: Optional[str] = None) -> StockEffect:
    """The answer for a call that raised where nothing could say how far it got (a route's belt-and-braces catch)."""
    return StockEffect(kind=kind, stopped_by=reason, reference=reference)


def guarded(kind: str, reference: Optional[str], work: Callable[[], StockEffect],
            on_error: Callable[[Exception], None]) -> StockEffect:
    """Run one of the four per-document stock functions from a route. They promise never to raise; if one breaks that promise
    the route's answer is a failure and not silence, and the route's own log line is `on_error`."""
    try:
        return work()
    except Exception as exc:  # noqa: BLE001 - the promise is the function's, the answer is ours
        on_error(exc)
        return failed(kind, type(exc).__name__, reference)


def attach(document: dict, effect: Optional[StockEffect]) -> dict:
    """Put the answer on the document a route is about to return, when stock is involved. Absent means "no goods line"
    and never "all well", so a document that moved no stock carries no key at all."""
    answer = effect.as_dict() if effect is not None else None
    if answer is not None:
        document["stock_effect"] = answer
    return document
