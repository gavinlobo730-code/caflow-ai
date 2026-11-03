"""Finding the documents whose stock effect was not all recorded, and completing it (POST-A-092, items 1, 2 and 4).

THE DOOR IS NARROW ON PURPOSE. This module decides nothing about stock or money: it finds a document, refuses the ones a retry
would be wrong for, and calls the same four functions a first issue calls (`inventory_service.apply_*_to_inventory`) with
`resume=True`. What those functions do on a retry, and what they refuse, is `domain/inventory/stock_resume`.

FINDING. `documents_with_unrecorded_stock` (migration 579) answers in one round trip with the documents of one client that have an
owed goods line and fewer stock rows than lines, or a stock row with a value and no journal. It is asked through the server's
privileged client AFTER the route has proved the caller's access to the client; a read that fails is `None` and never an empty
list, because an empty list here means "every goods document has its stock", and a failure must not look like that.

RETRYING. One document, named by kind and id, which must be this firm's AND this client's, issued (not a draft, not cancelled, not
deleted) and not an opening balance (those post no stock). A missing document and another client's document are the same refusal in
the same words. A retry holds an in-process lock on the document, so two clicks do not both write the missing line; the lock is right
for one worker and not for several, the same limit the rate windows record.

A CLOSED YEAR REFUSES FIRST. The document's own date is asked of the closures (`period_lock_service.assert_not_closed`) before the
claim and before any write, so a retry never leaves a stock row standing in a year the kernel would refuse the journal for.

WHAT A RETRY PRICES AT. Stock is costed in the order movements are RECORDED (`_last_ledger_row`), so a line recorded now takes the
item's cost as it stands now, not as it stood on the document's date. That is how a back-dated receipt or sale already behaves in
this ledger, and the retry does not pretend otherwise. The movement and its journal carry the document's own date.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Optional

from core import db_provider
from domain.inventory import stock_effect as stock_effects

_logger = logging.getLogger("caflow.stock_effect_retry")


@dataclass(frozen=True)
class _Kind:
    table: str
    number_column: str
    date_column: str
    #: the keyword the apply function takes the document under
    param: str
    #: the name of the apply function on `domain.inventory_service`
    apply_name: str
    opening_column: bool


KINDS = {
    "sales_invoice": _Kind("client_sales_invoices", "invoice_no", "invoice_date", "invoice", "apply_sale_to_inventory", True),
    "purchase_bill": _Kind("purchase_bills", "bill_no", "bill_date", "bill", "apply_purchase_to_inventory", True),
    "credit_note": _Kind("credit_notes", "credit_note_no", "credit_note_date", "credit_note", "apply_credit_note_to_inventory", False),
    "debit_note": _Kind("debit_notes", "debit_note_no", "debit_note_date", "debit_note", "apply_debit_note_to_inventory", False),
}
assert set(KINDS) == set(stock_effects.DOCUMENTS), "every document kind the sentences know has a retry"

#: What the status of a document that is not in the books says about its stock.
_NOT_LIVE = {
    "draft": "is still a draft",
    "cancelled": "was cancelled",
}


class NotFound(Exception):
    """No such document for this firm and client. The words are the same whether it is absent or another client's."""


class Refused(Exception):
    """The document is real and a retry is wrong for it. The message is the sentence for the screen."""


_locks_guard = threading.Lock()
_in_flight: set = set()


def _claim(key: tuple) -> bool:
    with _locks_guard:
        if key in _in_flight:
            return False
        _in_flight.add(key)
        return True


def _release(key: tuple) -> None:
    with _locks_guard:
        _in_flight.discard(key)


def server_db(request_db):
    """The privileged client where there is one, the caller's own where there is not (mock mode, a test double)."""
    if not request_db:
        return request_db
    return db_provider.service_db_or_none() or request_db


def unrecorded_documents(db, *, firm_id: str, client_id: str) -> Optional[dict]:
    """`{"total": n, "documents": [...]}` for one client, or None when the database could not be asked. The caller has proved the
    caller's access to `client_id`; this names the firm itself."""
    if not firm_id or not client_id:
        return None
    try:
        resp = server_db(db).rpc("documents_with_unrecorded_stock", {"p_firm": firm_id, "p_client": client_id}).execute()
    except Exception as exc:  # noqa: BLE001 - a failed read is a "could not check", never an empty list
        _logger.error("documents_with_unrecorded_stock failed for client %s: %s", client_id, type(exc).__name__)
        return None
    data = getattr(resp, "data", None)
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict) or not isinstance(data.get("documents"), list):
        return None
    try:
        total = int(data.get("total"))
    except (TypeError, ValueError):
        return None
    return {"total": total, "documents": data["documents"]}


def _load(db, kind: str, *, firm_id: str, client_id: str, document_id: str) -> dict:
    """The document, bound to the firm AND the client; absent and another client's are the same `NotFound`. One literal table per kind
    (not a table named by a variable), so a reader of the tree can see the scope on each statement."""
    if kind == "sales_invoice":
        query = db.table("client_sales_invoices").select("*").eq("id", document_id).eq("firm_id", firm_id).eq("client_id", client_id)
    elif kind == "purchase_bill":
        query = db.table("purchase_bills").select("*").eq("id", document_id).eq("firm_id", firm_id).eq("client_id", client_id)
    elif kind == "credit_note":
        query = db.table("credit_notes").select("*").eq("id", document_id).eq("firm_id", firm_id).eq("client_id", client_id)
    else:
        query = db.table("debit_notes").select("*").eq("id", document_id).eq("firm_id", firm_id).eq("client_id", client_id)
    rows = query.limit(1).execute().data or []
    if not rows:
        raise NotFound(document_id)
    return rows[0]


def retry(db, *, firm_id: str, client_id: str, kind: str, document_id: str, created_by: Optional[str]) -> dict:
    """Complete one document's stock effect. Returns `{"recorded", "message", "stock_effect"}`; raises `NotFound` or `Refused`."""
    spec = KINDS.get(kind)
    if spec is None:
        raise Refused("That kind of document does not move stock.")
    document = _load(db, kind, firm_id=firm_id, client_id=client_id, document_id=document_id)
    noun = stock_effects.DOCUMENTS[kind][0]
    reference = document.get(spec.number_column)
    subject = f"{noun} {reference}" if reference else f"this {noun}"
    label = subject[0].upper() + subject[1:]
    if document.get("deleted_at"):
        raise Refused(f"{label} was deleted, so there is no stock effect to complete.")
    status = str(document.get("status") or "").lower()
    if status in _NOT_LIVE:
        raise Refused(f"{label} {_NOT_LIVE[status]}, so it has no stock effect to complete.")
    if spec.opening_column and document.get("is_opening"):
        raise Refused(f"{label} is an opening balance carried over from the old books, which moves no stock here.")

    # A year the firm locked, or this client's finalised year-end, takes no new stock row or journal: asked BEFORE anything is written,
    # because the journal behind a line the kernel would refuse would be left unposted while the stock row stood in a closed year, and
    # closing stock as at that year-end would move on its own. The same closures the posting kernel asks (a filed return is not one:
    # a stock effect declares nothing in a return). Raises 422 with the closure's own sentence.
    from services import period_lock_service
    period_lock_service.assert_not_closed(db, firm_id, client_id, document.get(spec.date_column))

    key = (kind, str(document_id))
    if not _claim(key):
        raise Refused(f"A retry for {subject} is already running. Wait for it to finish.")
    try:
        from domain import inventory_service
        apply = getattr(inventory_service, spec.apply_name)
        effect = stock_effects.guarded(
            kind, reference,
            lambda: apply(db, firm_id=firm_id, client_id=client_id, created_by=created_by, resume=True,
                          **{spec.param: document}),
            lambda exc: _logger.error("stock retry for %s %s failed: %s", kind, document_id, type(exc).__name__),
        )
    finally:
        _release(key)

    answer = effect.as_dict()
    if answer is None:
        return {"recorded": None, "stock_effect": None,
                "message": f"{label} carries no goods line that stock is involved in, so there is nothing to complete."}
    if answer["recorded"]:
        return {"recorded": True, "stock_effect": answer, "message": f"The stock for {subject} is recorded in full."}
    return {"recorded": False, "stock_effect": answer, "message": answer["problem"]}
