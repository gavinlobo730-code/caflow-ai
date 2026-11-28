"""What a credit or debit note may be issued against (CGST Act s.34; ledger POST-A-579).

The four note routers (a sales credit note and debit note against an invoice, a purchase credit note and debit note against a bill)
each asked the same two questions of the document they apply a note to, in the same words, before moving its settled amount:

  * is it live? A draft was never issued (no receivable or payable exists to move) and a cancelled one is terminal;
  * is it billed in rupees? A note moves the rupee amount and carries no foreign one, so against a document billed in a foreign
    currency it would leave the document disagreeing with itself (`domain.accounting.foreign_documents` says why and holds the
    sentence). Refused before anything is written.

One function asks both, so a fifth door cannot ask one and forget the other, and the routers' issue functions, which the lint ratchet
holds to a size, do not each carry the branches.
"""
from __future__ import annotations

from fastapi import HTTPException

from domain.accounting import foreign_documents as _foreign


def assert_a_note_can_reach(document: dict, *, is_bill: bool, note: str, number: str, cannot: str) -> None:
    """Raise a 422 in words if `document` cannot take a `note` ("credit note" or "debit note").

    `cannot` is the verb the existing refusal for a draft or cancelled document used ("credit", "credit-note", "debit-note"); it is
    kept so that sentence is word for word what it was."""
    status = document.get("status") or ""
    noun = "bill" if is_bill else "invoice"
    if status in ("draft", "cancelled"):
        raise HTTPException(status_code=422, detail=f"Cannot {cannot} a {status} {noun}.")
    if _foreign.is_foreign(document):
        raise HTTPException(status_code=422, detail=_foreign.refusal_for_a_note(number, _foreign.billed_in(document), is_bill=is_bill, note=note))
