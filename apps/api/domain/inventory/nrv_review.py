"""A review of net realisable value across the whole stock register, posted as one batch (POST-A-111, the rest of INV-10).

WHAT WAS MISSING
    AS 2 carries inventories at the lower of cost and net realisable value, and the write-down to NRV existed one item at a
    time (`POST /api/inventory/items/{id}/writedown`, a modal opened from a register row). A year-end valuation is a review of
    the whole register: the CA reads each item's quantity and carrying value, decides which have fallen below cost, and
    records the NRV they have estimated for those. Doing that one modal at a time is the hundred-clicks path the physical
    count (INV-08) was built to replace.

WHAT THIS MODULE IS, AND IS NOT
    It is the SHEET: which items are on it, what each one holds now, and what the NRV the CA typed would write down. It
    holds no NRV of its own and suggests none: an item the CA typed nothing for is "not entered", never "at cost", and no
    figure on it (the average cost, a selling price, an ageing band) is offered as an estimate of NRV. NRV is the CA's
    judgement; the product records it and works out what it does.

    The arithmetic is `domain/inventory_service.nrv_writedown_answer`, which runs `_compute_nrv_writedown`, the function the
    posting runs, on the item's latest ledger row. `services/nrv_review_service.py` reads the rows (one question for the
    whole register, `stock_latest_rows`) and posts through `apply_nrv_writedown`, once per line, the SAME function the
    single-item door calls. One write path.

THE SHEET IS THE STOCK HELD NOW
    The write-down is measured on each item's latest ledger row, the same row the single-item door reads, so the sheet is
    the position as it stands, not as at a date. A write-down dated earlier is still measured on today's quantity and
    carrying value; the sheet says so (`MEASURED_NOW`).
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Iterable, Mapping, Optional

from domain.money_sentence import rupee_text

#: The most lines one POSTING request may carry. Each line is several round trips to the database when it posts, and a request that
#: outlives the browser's wait is a request whose outcome the person cannot see; the screen posts a longer sheet in parts.
#: THE PREVIEW HAS NO SUCH CAP, and must not (the review of POST-A-111): the screen asks it for every typed line at once, it reads
#: the whole register in one question whatever it is asked, and its lines are bounded already by the client's own goods (a line
#: naming anything else is refused, and so is an item named twice). A cap there refused a register of more than 100 typed lines
#: outright, so a sheet that size could never be worked out and so never posted.
MAX_LINES = 100

NOT_ENTERED = "not_entered"
WRITE_DOWN = "write_down"
NOT_BELOW = "not_below_carrying_value"
NO_STOCK = "no_stock"

MEASURED_NOW = (
    "Each figure is the item's stock as it stands now, the position a write-down is measured on. A write-down dated earlier "
    "is still measured on today's quantity and carrying value."
)

NO_NRV_OF_OUR_OWN = (
    "Net realisable value is your estimate for each item. Nothing on this sheet is a suggestion of it: an item you leave "
    "blank is not written down and is not taken to be at cost."
)


def lines_problem(item_ids: Iterable[str], *, capped: bool = True) -> Optional[str]:
    """The one refusal a request's lines can earn before anything is read: none, too many, or one item twice.

    An item named twice would be written down twice in one request (the second line measured on the first one's result),
    so it is refused rather than taken as either figure. `capped` is the posting's question; the preview asks with it off
    (see `MAX_LINES`) and is still refused an item named twice."""
    ids = [str(i) for i in item_ids]
    if not ids:
        return "Enter a net realisable value for at least one item."
    if capped and len(ids) > MAX_LINES:
        return f"A review can post at most {MAX_LINES} items in one request; this one names {len(ids)}."
    seen: set[str] = set()
    twice = sorted({i for i in ids if i in seen or seen.add(i)})
    if twice:
        return ("An item is named more than once. Enter one net realisable value for each item."
                if len(twice) == 1 else
                f"{len(twice)} items are named more than once. Enter one net realisable value for each item.")
    return None


def unknown_items_problem(item_ids: Iterable[str], goods_ids: Iterable[str]) -> Optional[str]:
    """A line that names something that is not one of this client's stock-tracked products. A missing item and another
    client's item read the same, as everywhere in the API."""
    known = {str(g) for g in goods_ids}
    unknown = [i for i in item_ids if str(i) not in known]
    if not unknown:
        return None
    if len(unknown) == 1:
        return "One line names an item that is not one of this client's stock-tracked products."
    return f"{len(unknown)} lines name items that are not this client's stock-tracked products."


def _qty(row: Optional[Mapping]) -> Decimal:
    if not row:
        return Decimal("0")
    try:
        return Decimal(str(row.get("running_qty_units")))
    except (InvalidOperation, TypeError):
        return Decimal("0")


def sheet_row(item: Mapping, latest: Optional[Mapping], nrv_per_unit_paise: Optional[int]) -> dict:
    """One item of the sheet: what it holds now and, where the CA typed an NRV, what that NRV writes down."""
    from domain.inventory_service import nrv_writedown_answer

    qty = _qty(latest)
    base = {
        "service_catalogue_id": str(item["id"]),
        "name": item.get("name") or "",
        "unit": item.get("unit"),
        "quantity_units": str(qty),
        "carrying_value_paise": int((latest or {}).get("running_value_paise") or 0) if qty > 0 else 0,
        "average_cost_paise": int((latest or {}).get("running_avg_cost_paise") or 0) if qty > 0 else 0,
        "nrv_per_unit_paise": nrv_per_unit_paise,
        "write_down_paise": None,
        "new_value_paise": None,
    }
    if nrv_per_unit_paise is None:
        return {**base, "status": NOT_ENTERED}
    answer = nrv_writedown_answer(latest if qty > 0 else None, int(nrv_per_unit_paise))
    if not answer["has_stock"]:
        return {**base, "status": NO_STOCK, "write_down_paise": 0, "new_value_paise": 0}
    return {
        **base,
        "carrying_value_paise": answer["carrying_value_paise"],
        "status": WRITE_DOWN if answer["needed"] else NOT_BELOW,
        "write_down_paise": answer["write_down_paise"],
        "new_value_paise": answer["new_value_paise"],
    }


def build_sheet(goods: Iterable[Mapping], latest: Mapping[str, Mapping], typed: Mapping[str, int]) -> dict:
    """The sheet: every good that holds stock now, in the order given (the register's), and every good the CA typed an NRV
    for even if it holds none (so a typed line is never dropped without a word). Totals are over the rows shown."""
    rows: list[dict] = []
    for g in goods:
        gid = str(g["id"])
        row = latest.get(gid)
        if _qty(row) <= 0 and gid not in typed:
            continue
        rows.append(sheet_row(g, row, typed.get(gid)))
    entered = [r for r in rows if r["status"] != NOT_ENTERED]
    writing = [r for r in rows if r["status"] == WRITE_DOWN]
    return {
        "items": rows,
        "item_count": len(rows),
        "entered_count": len(entered),
        "write_down_count": len(writing),
        "carrying_value_paise": sum(r["carrying_value_paise"] for r in rows),
        "write_down_paise": sum(int(r["write_down_paise"] or 0) for r in writing),
        "measured_now": MEASURED_NOW,
        "no_nrv_of_our_own": NO_NRV_OF_OUR_OWN,
    }


def posting_sentence(*, reference_no: str, posted: list[dict], not_needed: list[dict], failed: list[dict]) -> str:
    """What a posted batch did, in one paragraph a person reads. Rupees, never paise (`domain/money_text`)."""
    parts: list[str] = []
    total = sum(int(p.get("write_down_paise") or 0) for p in posted)
    if posted:
        parts.append(
            f"{len(posted)} {'item was' if len(posted) == 1 else 'items were'} written down to net realisable value under "
            f"{reference_no}, {rupee_text(total, '₹')} in all.")
    else:
        parts.append("Nothing was written down.")
    no_journal = [p for p in posted if p.get("journal_posted") is False]
    unknown_journal = [p for p in posted if p.get("journal_posted") is None]
    if no_journal:
        parts.append(
            ("The write-down was" if len(posted) == 1 else
             f"{len(no_journal)} of the write-downs {'was' if len(no_journal) == 1 else 'were'}")
            + " recorded in the stock ledger with no journal behind it, so the Inventory account still carries the value before "
              "the write-down; each such item is named below.")
    if unknown_journal:
        parts.append(
            ("Whether the write-down has" if len(posted) == 1 else
             f"Whether {len(unknown_journal)} of the write-downs {'has' if len(unknown_journal) == 1 else 'have'}")
            + " a journal behind it could not be read just now; the item's stock ledger shows it.")
    if not_needed:
        parts.append(
            f"{len(not_needed)} {'line was' if len(not_needed) == 1 else 'lines were'} left as {'it was' if len(not_needed) == 1 else 'they were'}: "
            "the value entered times the quantity held is not below the carrying value, or the item holds no stock.")
    if failed:
        parts.append(
            f"{len(failed)} {'line' if len(failed) == 1 else 'lines'} could not be recorded just now and nothing was posted for "
            f"{'it' if len(failed) == 1 else 'them'}. Posting the same sheet again writes down only what is still above the value "
            "you entered.")
    return " ".join(parts)
