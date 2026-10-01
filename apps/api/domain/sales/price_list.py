"""Price lists: which rate a line is PRE-FILLED with (accounting-20, migration 459).

READ THIS FIRST: A PRICE LIST IS A PRE-FILL SOURCE AND NOTHING ELSE.
`service_catalogue.default_rate_paise` is already a hint — the catalogue's own
module says "the stored rate/price are pre-fill hints, CGST Rule 46(g) — never
used in tax/journal math" — and a price list is a second hint of the same kind,
keyed on the customer. A trading client who quotes a dealer, a retailer and a
wholesaler three rates used to remember each one and type it onto every line.

IT CHANGES NO TAX AND NO POSTING, AND THE INVOICE KEEPS WHATEVER RATE IT WAS
GIVEN. The sales-invoice create path never reads a price list: the rate on a
line is the rate in the request, whatever put it there — a price list, the
catalogue, or a CA overwriting both. That is what makes this safe to add to a
product whose invoices feed GSTR-1: nothing here can move a figure that was not
typed or accepted on the line. The browser asks `resolve` when a catalogue item
is PICKED, and the answer lands in the rate box, where it stays editable.

THE ANSWER SAYS WHERE IT CAME FROM, in three states that are not interchangeable:

  * `price_list`  — the customer's default list has a rate for the item.
  * `catalogue`   — it does not, so the catalogue rate stands. The note says WHY
                    (no list, the list is archived, the list has no price for
                    this item), because a CA who expects the Dealer rate and
                    sees the catalogue rate needs to know which of those it was.
  * `none`        — neither holds a rate. The rate is None, never 0: the
                    catalogue's own "0 means no default price" is a state, not a
                    price, and a pre-filled 0 would be a free line nobody chose.

NOTHING IS COMPUTED. No discount, no mark-up, no percentage of another list: a
rate is a stated number of paise. A rate must be strictly positive, for the
reason above — a list rate of 0 would be indistinguishable from "this list has no
price for the item", and a genuinely free line is typed on the invoice, where it
is visible.

A LIST IS ARCHIVED, NOT DELETED. A customer pointing at an archived list falls
back to the catalogue rate and the answer says so, rather than the pointer
silently breaking.
"""
from __future__ import annotations

from typing import Optional

SOURCE_PRICE_LIST = "price_list"
SOURCE_CATALOGUE = "catalogue"
SOURCE_NONE = "none"

MAX_NAME_LENGTH = 80


def normalise_name(name) -> str:
    """Spacing collapsed, so "Dealer  A" and "Dealer A" are one name. The database
    index also ignores case; the service compares the same way."""
    return " ".join(str(name or "").split())


def name_problem(name) -> Optional[str]:
    clean = normalise_name(name)
    if not clean:
        return "A price list needs a name."
    if len(clean) > MAX_NAME_LENGTH:
        return f"A price list name is at most {MAX_NAME_LENGTH} characters."
    return None


def rate_problem(rate_paise) -> Optional[str]:
    """Whole paise, strictly positive. A bool is not an amount."""
    if isinstance(rate_paise, bool) or not isinstance(rate_paise, int) or rate_paise <= 0:
        return ("A price is a positive whole number of paise. To leave an item off a list, "
                "remove it — the catalogue rate then applies.")
    return None


def _positive(value) -> Optional[int]:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def resolve(*, list_id: Optional[str], list_name: Optional[str], list_active: bool,
            list_rate_paise, catalogue_rate_paise) -> dict:
    """The pre-fill for one (customer, item): a rate or None, where it came from,
    and — when the catalogue rate stands in for a list the CA might expect — why.

    The inputs are already fetched: whether the customer HAS a list, whether it is
    still active, the list's rate for this item (None where it has none) and the
    catalogue's default rate (0 or None where there is none)."""
    catalogue = _positive(catalogue_rate_paise)
    base = {"price_list_id": None, "price_list_name": None}

    def fall_back(note: Optional[str]) -> dict:
        if catalogue is not None:
            return {**base, "rate_paise": catalogue, "source": SOURCE_CATALOGUE, "note": note}
        return {**base, "rate_paise": None, "source": SOURCE_NONE,
                "note": (note + " " if note else "") + "No rate is recorded for this item either."}

    if not list_id:
        return fall_back(None)
    label = list_name or "the customer's price list"
    if not list_active:
        return {**fall_back(f"The price list {label} is archived, so the catalogue rate is used."),
                "price_list_id": list_id, "price_list_name": list_name}
    rate = _positive(list_rate_paise)
    if rate is None:
        return {**fall_back(f"The price list {label} has no price for this item, so the "
                            "catalogue rate is used."),
                "price_list_id": list_id, "price_list_name": list_name}
    return {"rate_paise": rate, "source": SOURCE_PRICE_LIST, "price_list_id": list_id,
            "price_list_name": list_name,
            "note": f"Pre-filled from the price list {label}. Edit the rate on the line if "
                    "this invoice should differ."}
