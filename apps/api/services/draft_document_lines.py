"""Replace the lines of a DRAFT document in one transaction (ledger POST-A-332).

WHY THIS IS ONE CALL
    A draft invoice, bill or note had its lines replaced as a DELETE and then an INSERT, two requests, and the header updated after
    both. A session that issued the document between the two left an ISSUED document with no lines: the insert was refused by the
    draft rule of migration 539 and the saver saw a generic failure. `public.replace_draft_document_lines` (migration 559) takes the
    header FOR UPDATE first, refuses in words when the document is no longer a draft, and replaces the lines in the one transaction
    the call is. This module is the one door to it: the six routers call `replace_draft_lines` and none of them deletes a draft's
    lines itself (`tests/test_the_lines_of_a_draft_are_replaced_through_one_call.py` holds that over the source).

WHAT IT DOES WHEN THE FUNCTION IS NOT THERE
    The API and the migration reach production at different moments. While the function is missing (PGRST202, or "function ... does
    not exist": the classifier the receipt and fee-billing services use) the old two-step replacement runs and a warning is logged;
    the fallback is deleted once migration 559 is on production. Any other error is the caller's.

WHAT IT DOES NOT DO
    It does not update the header. The header's totals are written by the route afterwards, as before, and the issue routes ask the
    draft whether it adds up to its own lines (`draft_integrity_service`) before anything is posted.
"""
from __future__ import annotations

import logging

from fastapi import HTTPException

_logger = logging.getLogger("caflow.services")

#: kind -> (lines table, the line's foreign key, what the document is called in a sentence)
DOCUMENTS: dict[str, tuple[str, str, str]] = {
    "sales_invoice": ("client_sales_invoice_lines", "sales_invoice_id", "invoice"),
    "purchase_bill": ("purchase_bill_lines", "bill_id", "bill"),
    "credit_note": ("credit_note_lines", "credit_note_id", "credit note"),
    "debit_note": ("debit_note_lines", "debit_note_id", "debit note"),
    "sales_debit_note": ("sales_debit_note_lines", "debit_note_id", "debit note"),
    "purchase_credit_note": ("purchase_credit_note_lines", "credit_note_id", "credit note"),
}


def _function_is_missing(err: Exception) -> bool:
    s = str(err).lower()
    return "pgrst202" in s or ("function" in s and ("does not exist" in s or "could not find the function" in s))


def replace_draft_lines(db, document: str, document_id: str, firm_id: str, lines: list[dict]) -> int:
    """Replace every line of the draft `document_id` with `lines`; the number of lines now on it.

    `lines` may carry the foreign key (the routers build their rows with it); the function sets it from the document's own id.
    A document that is not found for the firm is a 404 and one that has been issued meanwhile a 409, in words, and nothing changed.
    """
    _lines_table, fk, noun = DOCUMENTS[document]
    rows = [{k: v for k, v in ln.items() if k != fk} for ln in lines]
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
        if not _function_is_missing(e):
            raise
        _logger.warning("replace_draft_document_lines is not in the database yet; replacing the %s's lines in two steps", noun)
    _two_step(db, document, document_id, rows)
    return len(rows)


def _two_step(db, document: str, document_id: str, rows: list[dict]) -> None:
    """The replacement the API made before migration 559, kept for the hour the function is not in the database. Every chain names
    its table as a literal, so the column and firm-scope guards read each one; the lines tables carry no firm of their own, and
    `document_id` is a draft the route has already read under the firm."""
    if document == "sales_invoice":
        db.table("client_sales_invoice_lines").delete().eq("sales_invoice_id", document_id).execute()
        if rows:
            db.table("client_sales_invoice_lines").insert([{**r, "sales_invoice_id": document_id} for r in rows]).execute()
    elif document == "purchase_bill":
        db.table("purchase_bill_lines").delete().eq("bill_id", document_id).execute()
        if rows:
            db.table("purchase_bill_lines").insert([{**r, "bill_id": document_id} for r in rows]).execute()
    elif document == "credit_note":
        db.table("credit_note_lines").delete().eq("credit_note_id", document_id).execute()
        if rows:
            db.table("credit_note_lines").insert([{**r, "credit_note_id": document_id} for r in rows]).execute()
    elif document == "debit_note":
        db.table("debit_note_lines").delete().eq("debit_note_id", document_id).execute()
        if rows:
            db.table("debit_note_lines").insert([{**r, "debit_note_id": document_id} for r in rows]).execute()
    elif document == "sales_debit_note":
        db.table("sales_debit_note_lines").delete().eq("debit_note_id", document_id).execute()
        if rows:
            db.table("sales_debit_note_lines").insert([{**r, "debit_note_id": document_id} for r in rows]).execute()
    elif document == "purchase_credit_note":
        db.table("purchase_credit_note_lines").delete().eq("credit_note_id", document_id).execute()
        if rows:
            db.table("purchase_credit_note_lines").insert([{**r, "credit_note_id": document_id} for r in rows]).execute()
