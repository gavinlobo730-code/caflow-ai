"""The bill-wise breakup of a client's opening balances (ACC-14).

CGST Act s.7 — bringing a balance forward is not a supply, so nothing here
computes or declares any tax. `domain/accounting/opening_documents.py` decides
what an opening document may be; this router decides nothing.

WHY `accounting.write` AND NOT `sales.write` / `purchase.write`
    An opening document is a migration fact about the client's books, not a
    sale or a purchase this client transacted. It is recorded on the Opening
    Balances screen beside the master opening figures it breaks up, and the
    same role that may set those should be able to break them up.
"""
import os
from typing import Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from domain.accounting import opening_documents as od
from services import opening_document_service as svc

router = APIRouter(prefix="/api/opening-documents", tags=["opening_documents"])


class OpeningDocumentIn(BaseModel):
    """One document the party still owed, or was owed, at the opening date.

    `outstanding_paise` is what is STILL OPEN — not the document's original
    face value. A bill part-paid before the migration is carried at its balance,
    because that balance is what ages and what the control account carries.
    """
    client_id: str
    kind: str
    party_id: str
    document_no: str
    document_date: str
    due_date: Optional[str] = None
    outstanding_paise: int
    notes: Optional[str] = None


class OpeningDocumentRowIn(BaseModel):
    """One spreadsheet row, as typed (accounting-05).

    Dates and the party are TEXT on purpose: reading a date and matching a name
    are the server's rules (`domain/spreadsheet_cells`,
    `domain/accounting/opening_document_import`), and a browser that did either
    would be a second implementation of it. `row` is the number the person saw in
    the preview, so a sentence that names it can be found.

    `outstanding_paise` is None where the browser could not read the cell as an
    amount. The row still arrives and is refused here with its number, rather than
    being dropped on the way and missing from the report.
    """
    row: int
    party: str = ""
    party_gstin: Optional[str] = None
    document_no: str = ""
    document_date: str = ""
    due_date: Optional[str] = None
    outstanding_paise: Optional[int] = None
    notes: Optional[str] = None


class OpeningDocumentBulkIn(BaseModel):
    client_id: str
    kind: str
    rows: list[OpeningDocumentRowIn]
    #: Judge every row and write nothing. The answer carries the reconciliation
    #: AS IT WOULD STAND, so the CA sees whether the parties will foot first.
    dry_run: bool = False


@router.get("/kinds")
def list_kinds(current_user: dict = Depends(rbac("accounting", "read"))):
    """The two kinds and what each is called, so a screen holds no vocabulary."""
    return api_response(True, {
        "kinds": [
            {"value": od.RECEIVABLE, "label": "Receivable",
             "party": "customer", "number": "Invoice number"},
            {"value": od.PAYABLE, "label": "Payable",
             "party": "vendor", "number": "Bill number"},
        ],
        # Said once, by the module that refuses it, so the screen never
        # paraphrases a statutory limit.
        "section_194_aggregate": od.SECTION_194_AGGREGATE_IS_NOT_CARRIED,
    })


@router.get("")
def list_documents(
    client_id: str = Query(...),
    kind: str = Query(od.RECEIVABLE),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    assert_client_access(current_user, client_id)
    if not os.environ.get("SUPABASE_URL"):
        return api_response(True, {"kind": kind, "documents": [],
                                   "documents_paise": 0,
                                   "opening_balance_paise": 0,
                                   "reconciliation": [],
                                   "unreconciled_parties": 0})
    from core.supabase_client import get_supabase
    return api_response(True, svc.listing(
        get_supabase(), current_user.get("firm_id"), client_id, kind))


@router.post("")
def add_document(
    data: OpeningDocumentIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, data.client_id)
    if not os.environ.get("SUPABASE_URL"):
        return api_response(True, {"id": "mock-opening-document",
                                   **data.model_dump()})
    from core.supabase_client import get_supabase
    from services.audit_service import log_event
    row = svc.create(
        get_supabase(), current_user.get("firm_id"), data.client_id,
        kind=data.kind, party_id=data.party_id, document_no=data.document_no,
        document_date=data.document_date, due_date=data.due_date,
        outstanding_paise=data.outstanding_paise, notes=data.notes,
        actor_id=current_user.get("id"))
    log_event(current_user.get("firm_id") or "", "opening_document",
              str(row.get("id") or ""), "create",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.post("/bulk")
def bulk_import(
    data: OpeningDocumentBulkIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Bring a client's open invoices or bills over from a spreadsheet (accounting-05).

    Every row is judged before any is written, each bad row comes back with its
    number and ALL its problems, the good rows still land, and uploading the same
    file again records nothing twice. `domain/accounting/opening_document_import`
    carries the argument; this decides nothing. Registered BEFORE the
    `/{document_id}` route so "bulk" is never read as a document id.

    Posts no journal, declares no tax and withholds nothing — an opening document
    is the breakup of a balance the ledger already carries, exactly as the single
    POST above.
    """
    assert_client_access(current_user, data.client_id)
    from domain.accounting import opening_document_import as imp
    rows = [imp.ImportRow(**r.model_dump()) for r in data.rows]
    if not os.environ.get("SUPABASE_URL"):
        return api_response(True, {
            "kind": data.kind, "dry_run": data.dry_run, "received": len(rows),
            "created": 0 if data.dry_run else len(rows),
            "would_create": len(rows) if data.dry_run else 0,
            "already_recorded": 0, "rejected": 0, "created_paise": 0,
            "would_create_paise": 0, "rows": [], "reconciliation": [],
            "unreconciled_parties": 0})
    from core.supabase_client import get_supabase
    from services.audit_service import log_event
    out = svc.bulk_create(
        get_supabase(), current_user.get("firm_id"), data.client_id,
        kind=data.kind, rows=rows, actor_id=current_user.get("id"),
        dry_run=data.dry_run)
    if not data.dry_run and out["created"]:
        # One entry for the import, with row numbers and no amounts beyond the
        # total: the table's own audit trigger records each document, and this
        # is the line that says they arrived together and from where.
        log_event(current_user.get("firm_id") or "", "opening_document",
                  data.client_id, "bulk_import",
                  actor_id=current_user.get("auth_user_id"),
                  actor_email=current_user.get("email"),
                  new_data={"kind": data.kind, "received": out["received"],
                            "created": out["created"],
                            "already_recorded": out["already_recorded"],
                            "rejected": out["rejected"],
                            "created_paise": out["created_paise"]})
    return api_response(True, out)


@router.delete("/{document_id}")
def remove_document(
    document_id: str,
    client_id: str = Query(...),
    kind: str = Query(od.RECEIVABLE),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, client_id)
    if not os.environ.get("SUPABASE_URL"):
        return api_response(True, {"id": document_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services.audit_service import log_event
    out = svc.remove(get_supabase(), current_user.get("firm_id"), client_id,
                     kind=kind, document_id=document_id)
    log_event(current_user.get("firm_id") or "", "opening_document",
              document_id, "delete",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"))
    return api_response(True, out)


@router.get("/reconciliation")
def reconciliation(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Both sides, party by party: the opening balance the ledger carries
    against the documents behind it. A difference means the ageing schedule
    does not foot to its own control account, which is why it is named."""
    assert_client_access(current_user, client_id)
    if not os.environ.get("SUPABASE_URL"):
        return api_response(True, {})
    from core.supabase_client import get_supabase
    return api_response(True, svc.reconciliation(
        get_supabase(), current_user.get("firm_id"), client_id))
