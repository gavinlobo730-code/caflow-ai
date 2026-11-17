"""A document whose stock effect the CA already put right by hand is MARKED SETTLED, and the mark says why (POST-A-092).

WHAT WAS MISSING
    `documents_with_unrecorded_stock` lists the issued documents that owe a stock movement and have none, or whose valued movement has no
    journal. What it shows is what the stock ROWS show, so a document the CA had already put right with a stock adjustment stayed listed for
    ever, and "Complete the stock" would have moved its goods a second time. Nothing recorded that the document was dealt with.

WHAT THIS MODULE IS, AND IS NOT
    It is the words and the one rule about the reason. It reads no database and moves no stock. `services/stock_effect_retry_service` holds
    the marks (migration 620) and `routers/inventory` offers them. A mark is the CA's statement about their own books; the product records it
    with the reason they typed, who made it and when, and offers to take it back. It does NOT check the claim: whether the adjustment really
    put the document right is not something the stock rows can say, which is why the reason is required and the mark is visible.
"""
from __future__ import annotations

from typing import Optional

#: The most a reason may say (the table's CHECK, migration 620).
MAX_REASON = 500

NO_REASON = "Say why the stock of this document is settled (for example the adjustment you made), so the mark says what it rests on."
REASON_TOO_LONG = f"The reason can be at most {MAX_REASON} characters."


def clean_reason(text) -> str:
    """The reason as it is kept: the words the person typed, with runs of white space made one space and the ends trimmed."""
    return " ".join(str(text or "").split())


def reason_problem(text) -> Optional[str]:
    """The sentence that says what is wrong with a reason, or None. Judged on the cleaned text, so a box of spaces is no reason."""
    cleaned = clean_reason(text)
    if not cleaned:
        return NO_REASON
    if len(cleaned) > MAX_REASON:
        return REASON_TOO_LONG
    return None


def settled_refusal(label: str, reason: str) -> str:
    """What "Complete the stock" says for a document that is marked: the mark is the CA's, so the stock is left alone."""
    return (f"{label} is marked as settled by hand ({reason}), so its stock is not completed here. "
            "Take the mark off first if the stock should still be completed.")


def marked(label: str) -> str:
    """What the screen says once a document is marked: it left the list, and nothing in the books or the stock was touched."""
    return (f"{label} is marked as settled by hand and is no longer listed. Its stock and its books were not touched: the mark records what you said, "
            "with who and when, and can be taken off.")


TAKEN_BACK = ("The mark is off. The document is listed again if its stock is still not all recorded, and Complete the stock is offered for it again.")


def already_marked(label: str) -> str:
    return f"{label} is already marked as settled by hand."


def not_listed(label: str) -> str:
    return (f"{label} is not on the list of documents whose stock was not all recorded, so there is nothing to mark. "
            "A mark settles a listed document.")


CANNOT_CHECK_THE_LIST = ("Could not check just now whether this document is on the list of documents whose stock was not all recorded. "
                         "Nothing was marked; try again in a moment.")
