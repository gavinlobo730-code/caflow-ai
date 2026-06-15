"""
Portal router — Client portal document requests, messages, and dues.

Provides the CA-facing API for managing client portal content:
  - Document requests (ask clients to upload files)
  - Messages (broadcast updates from CA to client)
  - Dues summary (outstanding invoices/fees for a client)

All monetary values stored in integer paise (₹1 = 100 paise) — never float.
"""
from fastapi import APIRouter, Query, Depends
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
import uuid
import os

from models.common import api_response
from core.permissions import rbac  # M1: applied to every endpoint below (was unauthenticated)
import domain.portal_service as portal_svc

router = APIRouter(prefix="/api/portal", tags=["portal"])

# ── Dual-path: use in-memory mock when SUPABASE_URL is not set ────────────────
_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _db():
    if _USE_MOCK:
        return None
    from core.supabase_client import get_supabase
    return get_supabase()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Pydantic request models ───────────────────────────────────────────────────

class CreateDocRequestBody(BaseModel):
    firm_id: str
    client_id: str
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    is_urgent: bool = False


class SendMessageBody(BaseModel):
    firm_id: str
    client_id: str
    text: str
    from_ca: bool = True


# ── Document Requests ─────────────────────────────────────────────────────────

@router.get("/document-requests")
def list_document_requests(
    firm_id: str = Query(...),
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("portal", "read")),
):
    """List all document requests for a client."""
    db = _db()
    if db is None:
        rows = portal_svc.list_document_requests(firm_id, client_id)
        return api_response(True, rows)

    res = (
        db.table("document_requests")
        .select("id, firm_id, client_id, title, description, is_urgent, status, fulfilled_at, due_date, created_at")
        .eq("firm_id", firm_id)
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .execute()
    )
    return api_response(True, res.data or [])


@router.post("/document-requests")
def create_document_request(
    body: CreateDocRequestBody,
    current_user: dict = Depends(rbac("portal", "write")),
):
    """Create a new document request from CA to client."""
    db = _db()
    if db is None:
        record = portal_svc.create_document_request(
            firm_id=body.firm_id,
            client_id=body.client_id,
            title=body.title,
            description=body.description,
            due_date=body.due_date,
            is_urgent=body.is_urgent,
        )
        return api_response(True, record)

    now = _now()
    record = {
        "id": str(uuid.uuid4()),
        "firm_id": body.firm_id,
        "client_id": body.client_id,
        "title": body.title,
        "description": body.description,
        "due_date": body.due_date,
        "is_urgent": body.is_urgent,
        "status": "pending",
        "fulfilled_at": None,
        "created_at": now,
    }

    res = db.table("document_requests").insert(record).execute()
    return api_response(True, res.data[0] if res.data else record)


@router.put("/document-requests/{request_id}/complete")
def complete_document_request(
    request_id: str,
    current_user: dict = Depends(rbac("portal", "write")),
):
    """Mark a document request as fulfilled."""
    db = _db()
    now = _now()

    if db is None:
        updated = portal_svc.complete_document_request(request_id)
        if updated is None:
            return api_response(False, None, "Document request not found")
        return api_response(True, updated)

    res = (
        db.table("document_requests")
        .update({"status": "fulfilled", "fulfilled_at": now})
        .eq("id", request_id)
        .execute()
    )
    return api_response(True, res.data[0] if res.data else {"id": request_id, "status": "fulfilled"})


# ── Messages ──────────────────────────────────────────────────────────────────

@router.get("/messages")
def list_messages(
    firm_id: str = Query(...),
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("portal", "read")),
):
    """List all portal messages for a client (CA → client broadcasts)."""
    db = _db()
    if db is None:
        rows = portal_svc.list_messages(firm_id, client_id)
        return api_response(True, rows)

    res = (
        db.table("portal_messages")
        .select("id, firm_id, client_id, text, from_ca, created_at")
        .eq("firm_id", firm_id)
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .execute()
    )
    return api_response(True, res.data or [])


@router.post("/messages")
def send_message(
    body: SendMessageBody,
    current_user: dict = Depends(rbac("portal", "write")),
):
    """Send a portal message from CA to client."""
    db = _db()
    if db is None:
        record = portal_svc.send_message(
            firm_id=body.firm_id,
            client_id=body.client_id,
            text=body.text,
            from_ca=body.from_ca,
        )
        return api_response(True, record)

    now = _now()
    record = {
        "id": str(uuid.uuid4()),
        "firm_id": body.firm_id,
        "client_id": body.client_id,
        "text": body.text,
        "from_ca": body.from_ca,
        "created_at": now,
    }

    res = db.table("portal_messages").insert(record).execute()
    return api_response(True, res.data[0] if res.data else record)


# ── Dues ──────────────────────────────────────────────────────────────────────

@router.get("/dues")
def get_dues(
    firm_id: str = Query(...),
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("portal", "read")),
):
    """
    Outstanding dues summary for a client.
    Returns unpaid/overdue transactions from the transactions table.
    All amounts are in integer paise — never float.
    """
    db = _db()
    if db is None:
        # Return empty mock — real data requires the transactions table
        return api_response(True, {"dues": [], "total_paise": 0, "overdue_count": 0})

    res = (
        db.table("transactions")
        .select("id, party_name, transaction_date, reference_no, total_paise, status")
        .eq("firm_id", firm_id)
        .eq("client_id", client_id)
        .neq("status", "posted")
        .order("transaction_date", desc=True)
        .execute()
    )
    dues = res.data or []
    summary = portal_svc.compute_dues_summary(dues)
    return api_response(True, summary)
