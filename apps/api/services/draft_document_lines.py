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

from fastapi import HTTPException

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


def replace_draft_lines(db, document: str, document_id: str, firm_id: str, lines: list[dict]) -> int:
    """Replace every line of the draft `document_id` with `lines`; the number of lines now on it.

    `lines` may carry the foreign key (the routers build their rows with it); the function sets it from the document's own id.
    A document that is not found for the firm is a 404 and one that has been issued meanwhile a 409, in words, and nothing changed.
    """
    _lines_table, fk, noun = DOCUMENTS[document]
    rows = [{k: v for k, v in ln.items() if k != fk} for ln in lines]
    # Written as the API, after the route has read the draft under its firm and client: the signed-in role holds no write on the lines
    # once the grant is taken away (POST-A-335), and the function itself refuses a document that is not the firm's.
    db = privileged_for(db)
    try:
        db.rpc("replace_draft_document_lines", {
            "p_document": document, "p_document_id": document_id, "p_firm_id": firm_id, "p_lines": rows,
        }).execute()
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
