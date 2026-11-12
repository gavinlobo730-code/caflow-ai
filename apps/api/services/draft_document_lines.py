"""Replace the lines of a DRAFT document in one transaction (ledger POST-A-332).

WHY THIS IS ONE CALL
    A draft invoice, bill or note had its lines replaced as a DELETE and then an INSERT, two requests, and the header updated after
    both. A session that issued the document between the two left an ISSUED document with no lines: the insert was refused by the
    draft rule of migration 539 and the saver saw a generic failure. `public.replace_draft_document_lines` (migration 560) takes the
    header FOR UPDATE first, refuses in words when the document is no longer a draft, and replaces the lines in the one transaction
    the call is. This module is the one door to it: the six routers call `replace_draft_lines` and none of them deletes a draft's
    lines itself (`tests/test_the_lines_of_a_draft_are_replaced_through_one_call.py` holds that over the source).

WHAT IT NO LONGER DOES
    Until 29-10-2026 it replaced the lines in two steps (a delete and then an insert) when the function was not in the database yet, for
    the hour between the API reaching production and migration 560 doing so. Migration 560 has been on production since 10:00 UTC
    that day, so the fallback is deleted: a missing function is now an error the caller sees and not a second way to write the lines.

WHAT IT DOES NOT DO
    It does not update the header. The header's totals are written by the route afterwards, as before, and the issue routes ask the
    draft whether it adds up to its own lines (`draft_integrity_service`) before anything is posted.
"""
from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from core.db_paging import fetch_all
from core.db_provider import privileged_for

#: kind -> (lines table, the line's foreign key, what the document is called in a sentence)
DOCUMENTS: dict[str, tuple[str, str, str]] = {
    "sales_invoice": ("client_sales_invoice_lines", "sales_invoice_id", "invoice"),
    "purchase_bill": ("purchase_bill_lines", "bill_id", "bill"),
    "credit_note": ("credit_note_lines", "credit_note_id", "credit note"),
    "debit_note": ("debit_note_lines", "debit_note_id", "debit note"),
    "sales_debit_note": ("sales_debit_note_lines", "debit_note_id", "debit note"),
    "purchase_credit_note": ("purchase_credit_note_lines", "credit_note_id", "credit note"),
}


#: kind -> the statement that reads a document's lines as they are now. One literal chain per table, so the firm-scope reader can
#: see each (a `.table(variable)` is a place a missing filter would not be found). A line table carries no firm of its own: the
#: route has already read the document under its firm and client, and a line is confined to it by its foreign key.
_READ = {
    "sales_invoice": lambda db, doc: db.table("client_sales_invoice_lines").select("*").eq("sales_invoice_id", doc),
    "purchase_bill": lambda db, doc: db.table("purchase_bill_lines").select("*").eq("bill_id", doc),
    "credit_note": lambda db, doc: db.table("credit_note_lines").select("*").eq("credit_note_id", doc),
    "debit_note": lambda db, doc: db.table("debit_note_lines").select("*").eq("debit_note_id", doc),
    "sales_debit_note": lambda db, doc: db.table("sales_debit_note_lines").select("*").eq("debit_note_id", doc),
    "purchase_credit_note": lambda db, doc: db.table("purchase_credit_note_lines").select("*").eq("credit_note_id", doc),
}


#: kind -> the statement that writes one line's unit, for the two documents whose issued state still takes a unit correction.
_WRITE_UNIT = {
    "sales_invoice": lambda db, line_id, doc, unit: db.table("client_sales_invoice_lines").update({"unit": unit}).eq("id", line_id).eq("sales_invoice_id", doc),
    "purchase_bill": lambda db, line_id, doc, unit: db.table("purchase_bill_lines").update({"unit": unit}).eq("id", line_id).eq("bill_id", doc),
}


def _read_lines(db, document: str, document_id: str) -> list[dict]:
    """Every line the document holds now, in the order the document shows them, read in keyset pages: a document with more lines than
    PostgREST's row cap (a bill built from an import) would otherwise be recorded short, and the audit log can never be corrected."""
    rows = fetch_all(lambda: _READ[document](db, document_id), key="id", label=f"{document} lines for the edit record")
    return sorted(rows, key=lambda r: (r.get("sort_order") if isinstance(r.get("sort_order"), int) else 0, str(r.get("id"))))


def _same_lines(previous: list[dict], new: list[dict]) -> bool:
    """True when the lines that replace a draft's are, line for line, what it held: each stored line projected onto the columns the
    new one carries (the stored one also has its id, its document and its timestamps). The editor re-sends every line on every save,
    so a note-only edit would otherwise write a copy of every line both ways beside a header row that says what changed."""
    if len(previous) != len(new):
        return False
    return all({k: old.get(k) for k in row} == row for old, row in zip(previous, new, strict=True))


def set_line_units(db, document: str, document_id: str, firm_id: str, units: Optional[dict], *, edited_by: dict) -> None:
    """Correct the unit of lines on an invoice or a bill, and record what each unit was (POST-A-424).

    A unit never touches a rate, a quantity or an amount, so it is the one edit an ISSUED invoice or a received bill still takes
    (it is a GSTR-1 table 12 particular: the UQC). It was written by each route in place, and since the edit record began a
    unit-only save wrote no audit row at all. One row for the document names each line whose unit changed, its old unit and its new
    one; a line whose unit was already the one sent is written and not recorded. `None` or an empty map is nothing to do."""
    if not units:
        return
    db = privileged_for(db)
    # `document_id` was read under the firm and the client by the route, and a line is confined to it by its foreign key.
    held = {r["id"]: r.get("unit") for r in _read_lines(db, document, document_id)}
    old: dict[str, object] = {}
    new: dict[str, object] = {}
    for line_id, unit in units.items():
        value = unit or "NOS"
        _WRITE_UNIT[document](db, line_id, document_id, value).execute()
        if line_id in held and held[line_id] != value:
            old[line_id], new[line_id] = held[line_id], value
    if new:
        from services.audit_service import log_document_edit
        log_document_edit(
            firm_id, document, document_id, {"line_units": old}, {"line_units": new},
            actor_id=edited_by.get("auth_user_id"), actor_email=edited_by.get("email"))


def replace_draft_lines(db, document: str, document_id: str, firm_id: str, lines: list[dict], *, edited_by: dict) -> int:
    """Replace every line of the draft `document_id` with `lines`; the number of lines now on it.

    `lines` may carry the foreign key (the routers build their rows with it); the function sets it from the document's own id.
    A document that is not found for the firm is a 404 and one that has been issued meanwhile a 409, in words, and nothing changed.

    IT RECORDS WHAT IT REPLACED (POST-A-424). The lines a draft held are read first (as the API, and in full) and written to the audit
    log beside the lines that replace them, as one row for this document by `edited_by` (the signed-in member), after the replacement
    has happened and only then. No row-level record of a line exists: the line tables carry no firm, so the capture trigger is not on
    them. A save that sends the lines the draft already holds records nothing, because nothing was replaced in substance. The read is
    made before the database function takes the header's lock, so two members saving one draft at the same moment can both record
    the same lines as the ones they replaced (POST-A-429). `edited_by` has no default, so a caller that replaces lines has to say
    whose edit it is."""
    _lines_table, fk, noun = DOCUMENTS[document]
    rows = [{k: v for k, v in ln.items() if k != fk} for ln in lines]
    # Written as the API, after the route has read the draft under its firm and client: the signed-in role holds no write on the lines
    # once the grant is taken away (POST-A-335), and the function itself refuses a document that is not the firm's.
    db = privileged_for(db)
    # READ AS THE API TOO (POST-A-424): the signed-in role holds no read on the document tables either (migration 551), and a read that
    # went through the caller's own client would find nothing and record "the lines were empty" beside lines that were not.
    previous = _read_lines(db, document, document_id)
    try:
        db.rpc("replace_draft_document_lines", {
            "p_document": document, "p_document_id": document_id, "p_firm_id": firm_id, "p_lines": rows,
        }).execute()
        if not _same_lines(previous, rows):
            from services.audit_service import log_document_edit
            log_document_edit(
                firm_id, document, document_id, None, {}, actor_id=edited_by.get("auth_user_id"), actor_email=edited_by.get("email"),
                old_lines=previous, new_lines=rows)
        return len(rows)
    except Exception as e:  # noqa: BLE001
        text = str(e)
        if "document_not_draft" in text:
            raise HTTPException(
                status_code=409,
                detail=f"This {noun} was issued while you were editing it, so its lines were not changed. "
                       "Reload it to see what was issued.") from e
        if "document_not_found" in text:
            raise HTTPException(status_code=404, detail=f"{noun.capitalize()} not found") from e
        raise
