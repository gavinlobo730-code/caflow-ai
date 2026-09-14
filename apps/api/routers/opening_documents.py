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
    from core.config import settings as _s
    if getattr(_s, "USE_MOCK_DATA", False):
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
    from core.config import settings as _s
    if getattr(_s, "USE_MOCK_DATA", False):
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


@router.delete("/{document_id}")
def remove_document(
    document_id: str,
    client_id: str = Query(...),
    kind: str = Query(od.RECEIVABLE),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, client_id)
    from core.config import settings as _s
    if getattr(_s, "USE_MOCK_DATA", False):
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
    from core.config import settings as _s
    if getattr(_s, "USE_MOCK_DATA", False):
        return api_response(True, {})
    from core.supabase_client import get_supabase
    return api_response(True, svc.reconciliation(
        get_supabase(), current_user.get("firm_id"), client_id))
