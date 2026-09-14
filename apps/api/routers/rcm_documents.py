"""The two documents a reverse-charge purchase owes (PUR-19).

Thin surface over `services/rcm_document_service.py`, which is in turn a fetch
layer over `domain/gst/rcm_documents.py`. Nothing here decides anything: which
document is due, what it says and what could not be stated are all the domain
module's answers, and this router serves them.

# CA REVIEW REQUIRED — the preview is confirmed before a document is issued.
# Nothing here transmits anything to any portal.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from domain.gst import rcm_documents as rd
from services import rcm_document_service as svc

router = APIRouter(prefix="/api/rcm-documents", tags=["rcm_documents"])


class IssueRcmDocumentIn(BaseModel):
    """What to issue, and against what.

    `client_id` is required even though the parent row carries one: the
    mount-level guard fires on a client_id in the body, and a row-addressed
    request that carries none is scoped on firm_id alone — which is how any
    member of the firm reaches another staff member's client.
    """
    client_id: str
    kind: str
    purchase_bill_id: Optional[str] = None
    purchase_payment_id: Optional[str] = None
    document_no: Optional[str] = None
    document_date: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("kind")
    @classmethod
    def known_kind(cls, v: str) -> str:
        value = (v or "").strip()
        if value not in rd.KINDS:
            raise ValueError(
                f"kind must be one of {', '.join(rd.KINDS)} — "
                f"s.31(3)(f) self-invoice or s.31(3)(g) payment voucher.")
        return value


def _mock_enabled() -> bool:
    from core.config import settings as _s
    return bool(getattr(_s, "USE_MOCK_DATA", False))


@router.get("/kinds")
def list_kinds(current_user: dict = Depends(rbac("accounting", "read"))):
    """The two kinds, their sections and their rules — so a screen holds labels
    and not statute."""
    return api_response(True, [
        {
            "kind": k,
            "section": rd.SECTION_FOR_KIND[k],
            "rule": rd.RULE_FOR_KIND[k],
            "hangs_off": ("purchase_bill" if k == rd.KIND_SELF_INVOICE
                          else "purchase_payment"),
            # The one difference a screen must not get wrong.
            "only_when_supplier_unregistered": k == rd.KIND_SELF_INVOICE,
        }
        for k in rd.KINDS
    ])


@router.get("/registration-states")
def list_registration_states(current_user: dict = Depends(rbac("accounting", "read"))):
    """The three answers to "is this supplier registered", served rather than
    copied — `unrecorded` is a real state and a screen that knows only two
    turns a named gap into a silent guess."""
    return api_response(True, list(rd.REGISTRATION_STATES))


@router.get("/preview/self-invoice")
def preview_self_invoice(
    client_id: str = Query(...),
    purchase_bill_id: str = Query(...),
    document_no: Optional[str] = Query(None),
    document_date: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """What a CGST Act s.31(3)(f) self-invoice for this bill would say, or why
    none is due. Writes nothing."""
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"kind": rd.KIND_SELF_INVOICE, "due": False,
                                   "reasons": [], "gaps": [], "particulars": None,
                                   "existing": None})
    from core.supabase_client import get_supabase
    return api_response(True, svc.preview_self_invoice(
        get_supabase(), firm_id=current_user.get("firm_id"),
        bill_id=purchase_bill_id, document_no=document_no,
        document_date=document_date))


@router.get("/preview/payment-voucher")
def preview_payment_voucher(
    client_id: str = Query(...),
    purchase_payment_id: str = Query(...),
    document_no: Optional[str] = Query(None),
    document_date: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """What a CGST Act s.31(3)(g) payment voucher for this payment would say, or
    why none is due. Writes nothing."""
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"kind": rd.KIND_PAYMENT_VOUCHER, "due": False,
                                   "reasons": [], "gaps": [], "particulars": None,
                                   "existing": None})
    from core.supabase_client import get_supabase
    return api_response(True, svc.preview_payment_voucher(
        get_supabase(), firm_id=current_user.get("firm_id"),
        payment_id=purchase_payment_id, document_no=document_no,
        document_date=document_date))


@router.get("")
def list_documents(
    client_id: str = Query(...),
    kind: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    assert_client_access(current_user, client_id)
    if kind and kind not in rd.KINDS:
        raise HTTPException(status_code=422, detail=f"Unknown kind {kind!r}.")
    if _mock_enabled():
        return api_response(True, [])
    from core.supabase_client import get_supabase
    return api_response(True, svc.listing(
        get_supabase(), firm_id=current_user.get("firm_id"),
        client_id=client_id, kind=kind))


@router.post("")
def issue_document(
    data: IssueRcmDocumentIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Issue the document.

    # CA REVIEW REQUIRED — the CA confirms the preview's particulars first.
    """
    assert_client_access(current_user, data.client_id)
    wants_bill = data.kind == rd.KIND_SELF_INVOICE
    if wants_bill and not data.purchase_bill_id:
        raise HTTPException(
            status_code=422,
            detail="A s.31(3)(f) self-invoice is issued against a purchase bill.")
    if not wants_bill and not data.purchase_payment_id:
        raise HTTPException(
            status_code=422,
            detail="A s.31(3)(g) payment voucher is issued against a payment — "
                   "the section dates it at the time of payment.")
    if _mock_enabled():
        return api_response(True, {"id": "mock-rcm-document", **data.model_dump()})

    from core.supabase_client import get_supabase
    from services.audit_service import log_event
    row = svc.issue(
        get_supabase(), firm_id=current_user.get("firm_id"), kind=data.kind,
        bill_id=data.purchase_bill_id, payment_id=data.purchase_payment_id,
        document_no=data.document_no, document_date=data.document_date,
        notes=data.notes, actor_id=current_user.get("id"))
    log_event(current_user.get("firm_id") or "", "rcm_document", row.get("id") or "",
              "issue", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              new_data={"kind": data.kind, "document_no": row.get("document_no"),
                        "document_date": str(row.get("document_date"))})
    return api_response(True, row)
