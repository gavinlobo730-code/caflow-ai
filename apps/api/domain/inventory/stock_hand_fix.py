"""Two kinds of purchase bill that "Complete the stock" cannot finish, and what the CA is told to do about each (POST-A-092, decided 27-11-2026).

WHAT WAS MISSING
    A retry writes what the stock step did not write: the goods lines with no stock row and the journal behind a valued row. Two shapes are
    outside what it can honestly do, and until migration 780 the screen did not say so before the press:
      * LANDED CHARGES. A bill with freight, insurance or duty recorded against it whose stock rows have no journal. The split of each charge over
        the goods is not kept on the row, so rebuilding the journal would be a guess about a ledger figure. The retry refuses it.
      * OVERSOLD TRUE-UP. A bill received while the item was already oversold: the cost of the units that covered the earlier sales belongs in
        Cost of Goods Sold, and a separate entry moves it. When that entry failed, a row of the bill is of NIL value (all of it covered earlier sales)
        or was written while the item's quantity was below nil (a part did), and the bill was never listed, because the finder only looked for a valued
        row with no journal.

WHAT THIS MODULE IS, AND IS NOT
    It is the two kinds and the words, nothing else. It reads no database, rebuilds no figure and posts nothing. The database finder says WHICH
    bills (`hand_fix` on each found document, migration 780); `services/stock_effect_retry_service` puts the sentence on the document it lists and
    refuses the retry with the same sentence; the screen shows it in place of the Complete the stock button. The CA puts the books right by hand and
    then marks the bill settled with a note of what they posted, which is the mark that already exists.

WHAT IT CANNOT DO
    It cannot say HOW MUCH: the amount of a true-up, and the split of a charge over the goods, are not kept on the stock row, so the sentences name
    what to post and leave the figure to the person who reads the books. A bill whose true-up was posted and later reversed on purpose is listed
    too, and the words say "it was never posted, or it was reversed".
"""
from __future__ import annotations

from typing import Optional

LANDED_CHARGES = "landed_charges"
OVERSOLD_TRUEUP = "oversold_trueup"
KINDS = (LANDED_CHARGES, OVERSOLD_TRUEUP)

_WHAT_NEXT = ("Then mark it as settled by hand, with a note of what you posted, and it leaves this list.")

_SAYS = {
    LANDED_CHARGES: (
        "{label} has freight, insurance or duty recorded against it, and its stock rows were written without their journal. "
        "The product cannot rebuild how each charge was spread over the goods, so it does not offer Complete the stock for it. "
        "Post by hand the journal that debits Inventory with the value this bill's rows show in the stock ledger and credits the expense accounts "
        "that value was booked to: the goods' own account and, where a charge is part of that value, the charge's account. "
        "A charge added after the bill was received is not part of that value. "
        + _WHAT_NEXT),
    OVERSOLD_TRUEUP: (
        "{label} received goods that covered units sold earlier while the item was oversold, so the cost of those units belongs in Cost of Goods Sold, "
        "and no entry for it stands (it was never posted, or it was reversed). The product does not offer Complete the stock for it. "
        "Post it by hand: debit Cost of Goods Sold with the cost of the units that covered the earlier sale and credit the expense accounts the bill and "
        "its charges were booked to. For a line whose stock row shows no value, that is the whole cost of the line (its taxable value, any tax on it that "
        "cannot be claimed as credit, and its share of any freight or duty); for a line that covered the earlier sale only in part, that part of it. "
        "If the bill is cancelled later, reverse that entry yourself. "
        + _WHAT_NEXT),
}


def known(kind) -> bool:
    return kind in KINDS


def says(kind: Optional[str], label: str) -> Optional[str]:
    """The sentence for a document the CA has to put right by hand, or None for a document a retry can finish (or a kind this module does not know)."""
    template = _SAYS.get(kind or "")
    return template.format(label=label) if template else None


def refusal(kind: str, label: str) -> str:
    """What "Complete the stock" answers for such a document if the request reaches the server: the same words, and that nothing was moved."""
    return f"{says(kind, label)} Nothing was moved."
