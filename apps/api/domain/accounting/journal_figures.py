"""Does a journal already in the ledger carry the figures a document is about to post? (ledger POST-A-092, the reuse half)

WHY THE QUESTION EXISTS
    The posting kernel is idempotent on (firm, client, reference number, entry date): when an entry for that number and date is already
    live it returns that entry's id and writes nothing. That is what makes a retry safe, and it is right for a retry of the SAME
    document. Issuing a draft invoice posts the journal first and then, in a separate statement, marks the invoice issued and links the
    journal. If the second statement fails (a network blip between Singapore and Mumbai, a restart) the invoice stays a draft with a
    live journal behind it, and the CA, who was told the issue failed, reasonably opens the draft and corrects it before trying again.
    The retry then finds the old journal under the invoice's number and date, links the invoice to it and reports success: the
    invoice says one thing, and the ledger, the output tax in GSTR-3B and the customer's balance say another, with nothing anywhere
    naming the difference.

WHAT IS COMPARED
    The lines, as (account, debit, credit) in paise, taken as a multiset: the order lines were written in and their narration do not
    matter, two lines of the same account and the same figures are two lines, and a line of nil on both sides is not a line. The
    entry's date and number are the key it was found by, so they cannot differ. Nothing is rounded and nothing has a tolerance: a
    tolerance on a posted figure is a posted figure that is wrong by that much.

WHAT IT DOES NOT DO
    It does not decide what to do about a difference. It words it, for a person, in rupees. The kernel refuses (the entry is not
    touched, the document stays a draft) and the person reverses the old entry from the ledger and issues again, or restores the
    draft to what it was. Nothing is posted, filed or changed here.
"""
from __future__ import annotations

from collections import Counter
from typing import Iterable, Optional

from domain.money_sentence import rupee_text

Figure = tuple  # (account_id, debit_paise, credit_paise)


class EntryCannotBeReused(ValueError):
    """An entry is already in the ledger under this number and date, and it is not known to carry the figures being posted: it
    carries other ones, or it could not be read to check.

    A ValueError so every caller that already stops on a refusal of the posting stops here; the sentence is for a person and is the
    whole of the message, so a router that wants to say it words nothing around it. `unreadable` is True when the refusal is only that
    the ledger could not be read: the posting still refuses on it (a check that cannot look is not a check), but a pre-flight, which is
    a reading and not a gate, must not tell a person an entry exists on that evidence."""

    def __init__(self, message: str, *, unreadable: bool = False):
        super().__init__(message)
        self.unreadable = unreadable


def unreadable(*, what: str, known_entry: bool = True) -> str:
    """The sentence for a ledger that could not be read to answer. Refusing is the only honest answer: a check that cannot look is not
    a check, and 'the same' is a claim.

    `known_entry` says whether an entry is KNOWN to be there. It is when the lookup by number and date has found one and it is the
    lines of that entry that could not be read; it is not when the lookup itself failed, or the lookup by source did, because then
    nothing is known to exist, and a sentence that says an entry is in the ledger would be a sentence the books do not support (the
    first version of this said it for both, found by the independent review of 8364b95f)."""
    if known_entry:
        return (f"An entry for {what} on this date is already in the ledger, and it could not be read just now to check that it carries "
                f"the figures {what} has. Nothing was changed. Try again in a moment.")
    return (f"The ledger could not be checked just now for an earlier entry of {what}, so nothing was done. Nothing was changed. "
            f"Try again in a moment.")


def _paise(value) -> int:
    return int(value or 0)


def figures_of(lines: Iterable[dict]) -> Counter:
    """The lines as a multiset of (account, debit, credit); a line with nothing on either side is not counted."""
    out: Counter = Counter()
    for line in lines or []:
        debit, credit = _paise(line.get("debit_paise")), _paise(line.get("credit_paise"))
        if debit == 0 and credit == 0:
            continue
        out[(str(line.get("account_id")), debit, credit)] += 1
    return out


def totals_of(figures: Counter) -> tuple[int, int]:
    """(total debit, total credit) of a multiset of figures."""
    debit = sum(d * n for (_a, d, _c), n in figures.items())
    credit = sum(c * n for (_a, _d, c), n in figures.items())
    return debit, credit


def difference(existing_lines: Iterable[dict], proposed_lines: Iterable[dict], *, what: str) -> Optional[str]:
    """None when the entry in the ledger carries exactly the figures being posted; otherwise one sentence for a person.

    `what` names the document in the sentence ("invoice INV/26-27/0042")."""
    held, wanted = figures_of(existing_lines), figures_of(proposed_lines)
    if held == wanted:
        return None
    held_total, wanted_total = totals_of(held)[0], totals_of(wanted)[0]
    if held_total != wanted_total:
        how = f"The entry in the ledger totals {rupee_text(held_total)} and {what} now comes to {rupee_text(wanted_total)}."
    else:
        how = f"The entry in the ledger and {what} both total {rupee_text(held_total)}, but not in the same lines."
    return (
        f"An entry for {what} on this date is already in the ledger and it does not carry the figures {what} has now. It may have "
        f"been left by an earlier issue that did not finish. {how} Nothing was changed. {_WHAT_NEXT}"
    )


# What a person can do about it. It is said the same for a draft and for an issued invoice, because the repost route reaches it too: an
# issued invoice's lines are locked, so "put the draft back" is offered only where it applies. Reversing a ledger entry is a Partner's.
_WHAT_NEXT = (
    "A Partner can reverse that entry from the ledger so the invoice can be posted afresh; if it is still a draft, it can instead be "
    "put back to what it was."
)


def elsewhere(*, what: str, number: str, date: str) -> str:
    """The sentence for an entry that belongs to this document (its source is the document) but is held under another number or date:
    the draft's number or date was corrected after an issue that did not finish. Posting again would put the document in the ledger
    twice, so nothing is posted."""
    return (
        f"An entry for {what} is already in the ledger, left by an earlier issue that did not finish, but under number {number} "
        f"dated {date}, which is not the number and date {what} has now. Posting it again would count it twice. Nothing was changed. "
        f"{_WHAT_NEXT}"
    )


def kept_by_delete(*, what: str, number: str, date: str) -> str:
    """The sentence for a draft that cannot be deleted because an earlier issue that did not finish left an entry for it in the ledger.
    Deleting the draft would leave that entry live with nothing behind it, and the next draft to take the same number on another date
    would post a second one beside it (the document counted twice)."""
    return (
        f"{what[:1].upper()}{what[1:]} cannot be deleted yet: an earlier issue that did not finish left an entry for it in the ledger "
        f"(number {number} dated {date}), and deleting the draft would leave that entry with nothing behind it. Nothing was changed. "
        f"A Partner can reverse that entry from the ledger first; then the draft can be deleted."
    )
