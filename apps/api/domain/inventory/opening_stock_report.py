"""What a bulk product import did about the opening stock its file asked for, and the sentence when it did not do all of it (POST-A-092, the bulk-import half).

WHY THIS EXISTS

`POST /api/service-catalogue/bulk` creates the products in one insert and then seeds an opening stock row for each goods
line that came with a quantity and a cost (`inventory_service.seed_opening_balances_batch`). The seeding is fail-soft on purpose:
a bad opening balance must never fail a 300-product import. The failure went to Sentry and nowhere else, and the route
answered a plain success, so the catalogue rows kept `opening_qty_units` and `opening_cost_paise` while the item's stock stayed
at 0, and the person who had just imported a stock list read "imported" for a list whose stock was not there.

This module turns the one thing the route can ask afterwards, which of the items that asked for an opening balance have an
opening row in the stock ledger, into the fact the route puts on its response and the sentence the screen prints, so the
wording is written once and not by the screen.

THE THREE STATES

    none asked          no goods line came with an opening balance: there is nothing to report and no sentence.
    recorded            every item that asked has its opening row.
    not recorded        some did not. The names are listed (up to five, then a count), because the person has to know which.
    could not check     the stock ledger could not be read, so nothing is claimed either way, and the sentence says so; "recorded"
                        is never inferred from a read that failed.

WHAT THIS DOES NOT DO

It does not retry the seeding and it does not change what the seeding writes. The journals of a batch whose ledger insert was
refused are reversed by the seeding itself (ledger POST-A-321); this only says what the stock ledger holds afterwards.
"""
from __future__ import annotations

from typing import Optional

#: The most names a sentence lists before it counts the rest.
_NAMES_LISTED = 5

REMEDY = "Adjust stock by hand once the cause is fixed."


def _plural(n: int) -> str:
    return "product" if n == 1 else "products"


def _names(rows: list) -> str:
    shown = [f"“{str(r.get('name') or 'unnamed').strip()}”" for r in rows[:_NAMES_LISTED]]
    more = len(rows) - len(shown)
    return ", ".join(shown) + (f" and {more} more" if more > 0 else "")


def report(asked: list, landed: Optional[set]) -> dict:
    """The answer for a batch. `asked` is the items that came with an opening balance the seeding would take (each a dict with
    an `id` and a `name`); `landed` is the ids among them that have an opening row in the stock ledger, or None when the
    ledger could not be read."""
    count = len(asked)
    if count == 0:
        return {"asked": 0, "recorded": 0, "not_recorded": [], "checked": True, "message": None}
    if landed is None:
        return {
            "asked": count, "recorded": None, "not_recorded": [], "checked": False,
            "message": (f"Opening stock was asked for on {count} {_plural(count)}, but the stock ledger could not be read to confirm "
                        "it was recorded. Look at the Stock column before relying on it."),
        }
    held = {str(i) for i in landed}
    missing = [r for r in asked if str(r.get("id")) not in held]
    recorded = count - len(missing)
    if not missing:
        return {"asked": count, "recorded": recorded, "not_recorded": [], "checked": True, "message": None}
    return {
        "asked": count, "recorded": recorded, "checked": True,
        "not_recorded": [{"id": r.get("id"), "name": r.get("name")} for r in missing],
        "message": (f"Opening stock was not recorded for {len(missing)} of {count} {_plural(count)}: {_names(missing)}. "
                    f"{'The product was' if len(missing) == 1 else 'These products were'} created without it, so the Stock column shows 0. {REMEDY}"),
    }
