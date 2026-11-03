"""A credit note or a purchase debit note says whether the goods it names physically came back (POST-A-371, migration 581).

WHY THIS EXISTS

`inventory_service.apply_credit_note_to_inventory` and `apply_debit_note_to_inventory` treated every goods line that named a catalogue
item as goods physically returned: a credit note restocked at the original sale's unit cost and posted Dr Inventory / Cr Cost of goods
sold, a debit note destocked and posted Dr Expense / Cr Inventory. A section 34 note is also the way to correct a PRICE, a DISCOUNT or an
EXCESS BILLED, and the note models make the catalogue pick mandatory on every line, so such a note on a goods item moved stock and cost
that never moved: phantom units in Inventory and a wrong cost of goods sold, with the tax side right.

The note now carries the answer as a stored fact, `goods_returned`: TRUE (goods came back, stock moves), FALSE (a correction, stock does
not move) or NULL (not stated: every note written before the column). Issuing a note that NAMES GOODS and has not stated it is REFUSED
in the sentence below, so the stock effect of a note is never assumed. An already-issued note with NULL moved stock under the old rule
and is still counted as owing it, because that is what was done.

WHAT THIS MODULE HOLDS: the question, the test for "names goods" (the same predicate the stock functions use, so the refusal and the
movement agree about what a goods line is), the answer for a note that says no goods came back, and nothing that touches a ledger.
The logic is here and in the routers, never in the browser.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

#: kind -> (the note as a person names it, how the goods "came back", what stock does when they have).
KINDS = {
    "credit_note": ("credit note", "came back", "added back to stock"),
    "debit_note": ("debit note", "went back to the supplier", "taken out of stock"),
}


def question(kind: str) -> str:
    """The refusal for a note that names goods and does not say whether they came back."""
    noun, came_back, did = KINDS[kind]
    return (
        f"This {noun} names goods. Say whether the goods physically {came_back} before you issue it: choose 'Goods returned' if they did "
        f"(they are {did} and the cost is posted), or 'No goods returned' for a price, rate or discount correction (stock and cost "
        f"do not move). The tax is adjusted either way."
    )


def declined(kind: str, reference: Optional[str]) -> str:
    """What the response says about stock when the note said no goods came back. Said, never left absent: an absent answer reads as 'no goods'."""
    noun, came_back, _did = KINDS[kind]
    ref = f" {reference}" if reference else ""
    return (f"Stock was not moved for {noun}{ref}: it says no goods {came_back} (a price, rate or discount correction). "
            f"If goods did move, record that with a stock adjustment.")


def _lines_of(db, kind: str, note_id: str) -> list[dict]:
    """The note's lines. One literal table per kind (not a table named by a variable), so a reader of the tree can see the scope on each
    statement; the note was fetched under its firm by the handler, and a line hangs from it."""
    if kind == "credit_note":
        query = db.table("credit_note_lines").select("id, quantity, service_catalogue_id").eq("credit_note_id", note_id)
    else:
        query = db.table("debit_note_lines").select("id, quantity, service_catalogue_id").eq("debit_note_id", note_id)
    return query.execute().data or []


def goods_lines_on_note(db, *, firm_id: str, client_id: str, kind: str, note_id: str) -> int:
    """How many lines of this note would move stock if it said goods came back: a line with a quantity that names THIS client's own
    stock-tracked goods item. The firm and client filters are what keep a line naming another firm's or client's item out; this is the
    predicate `inventory_service` applies, restated for the question and not for a movement."""
    lines = _lines_of(db, kind, note_id)
    item_ids = list({line["service_catalogue_id"] for line in lines if line.get("service_catalogue_id")})
    if not item_ids:
        return 0
    items = (db.table("service_catalogue").select("id, kind").in_("id", item_ids)
             .eq("firm_id", firm_id).eq("client_id", client_id).execute().data) or []
    goods = {i["id"] for i in items if i.get("kind") == "good"}
    return sum(1 for line in lines if line.get("service_catalogue_id") in goods and float(line.get("quantity") or 0) > 0)


def says_no_goods_came_back(note: dict) -> bool:
    """TRUE only for an explicit FALSE. NULL (not stated) is not a 'no'."""
    return note.get("goods_returned") is False


def must_say(note: dict, goods_lines: int) -> bool:
    """TRUE when the note names goods and has not stated whether they came back: the case issuing refuses."""
    return goods_lines > 0 and note.get("goods_returned") is None


def stated_column(data: dict) -> dict:
    """`{"goods_returned": v}` when the CA stated it, else `{}`. The column is written only when stated, because the API can be live a few
    minutes before migration 581 adds it (belt and braces: the schema guard also holds /health at 503 until the migration lands, so a deploy that booted early is held back), and a note that does not say (a service) must keep saving in that window. A stated answer on a
    database without the column fails loudly, which is right: the choice would otherwise be lost."""
    return {} if data.get("goods_returned") is None else {"goods_returned": data["goods_returned"]}


def refuse_unless_stated(db, kind: str, note: dict, *, firm_id: str, note_id: str) -> int:
    """The check at issue, before anything is posted: a note that names goods says whether they came back, or this raises the 422 in
    the sentence `question` writes. Returns how many goods lines the note names, which the response uses after the stock step."""
    named = goods_lines_on_note(db, firm_id=firm_id, client_id=note.get("client_id") or "", kind=kind, note_id=note_id)
    if must_say(note, named):
        raise HTTPException(status_code=422, detail=question(kind))
    return named


def attach_declined(note: dict, kind: str, names_goods: int) -> None:
    """Say it in the response when stock was left alone on purpose. Said, never left absent: an absent stock answer reads as 'no goods'.
    (The route attaches what the stock step DID, `stock_effects.attach`, itself and in its own handler, because the guards that read the
    routes look for that call there.)"""
    if names_goods and says_no_goods_came_back(note):
        number = note.get(f"{kind}_no")
        note["stock_not_moved"] = declined(kind, number)
