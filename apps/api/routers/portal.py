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
from core.authz import assert_client_access, can_access_client  # M2: assignment scope
import domain.portal_service as portal_svc
from services import portal_data_service  # Phase 4.5.2: canonical AR (retires `transactions` dues)

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
    client_id: str
    title: str
    description: Optional[str] = None
    due_date: Optional[str] = None
    is_urgent: bool = False


class SendMessageBody(BaseModel):
    client_id: str
    text: str
    from_ca: bool = True


def _assert_doc_request_scope(current_user: dict, request_id: str):
    """Resolve a document_requests row, without mutating it, and return None
    unless it belongs to the caller's firm and the caller may access its
    client — matching this router's existing convention of a 200 + {success:
    false} refusal (not a raised HTTPException) for "not found", so a missing
    request_id and an unassigned one read identically."""
    firm_id = current_user["firm_id"]
    db = _db()
    if db is None:
        row = portal_svc.get_document_request(request_id)
    else:
        res = db.table("document_requests").select("*").eq("id", request_id).execute()
        row = res.data[0] if res.data else None
    if not row or row.get("firm_id") != firm_id or not can_access_client(current_user, row.get("client_id")):
        return None
    return row


# ── Document Requests ─────────────────────────────────────────────────────────

@router.get("/document-requests")
def list_document_requests(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("portal", "read")),
):
    """List all document requests for a client."""
    # M2 audit finding: client_id was caller-supplied and never checked.
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    db = _db()
    if db is None:
        rows = portal_svc.list_document_requests(firm_id, client_id)
        return api_response(True, rows)

    res = (
        db.table("document_requests")
        # `due_date` is not a column on document_requests and never has been —
        # the table carries is_urgent as its only urgency signal. PostgREST
        # rejects the whole select at parse time, so this endpoint returned 500
        # on every call rather than degrading to a missing field. No caller
        # reads a due date off a document request, so it is dropped rather than
        # inventing a column to satisfy a select nobody depended on.
        .select("id, firm_id, client_id, title, description, is_urgent, status, fulfilled_at, created_at")
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
    # M2 audit finding: client_id was caller-supplied and never checked.
    assert_client_access(current_user, body.client_id)
    firm_id = current_user["firm_id"]
    db = _db()
    if db is None:
        record = portal_svc.create_document_request(
            firm_id=firm_id,
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
        "firm_id": firm_id,
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
    # M2 audit finding: row-addressed by request_id, checked only firm_id —
    # never checked the caller's assignment to its client.
    if _assert_doc_request_scope(current_user, request_id) is None:
        return api_response(False, None, "Document request not found")

    db = _db()
    now = _now()

    if db is None:
        updated = portal_svc.complete_document_request(request_id)
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
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("portal", "read")),
):
    """List all portal messages for a client (CA → client broadcasts)."""
    # M2 audit finding: client_id was caller-supplied and never checked.
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    db = _db()
    if db is None:
        rows = portal_svc.list_messages(firm_id, client_id)
        return api_response(True, rows)

    # The table stores `body` and `sender_type` ('ca'|'client'); this asked for
    # `text` and `from_ca`, neither of which exists, so the select was rejected
    # at parse time and the endpoint returned 500 on every call.
    #
    # The API shape is deliberately UNCHANGED. portal_service's mock path (the
    # branch above) returns text/from_ca, so that is the contract callers were
    # written against — the fix belongs at the database boundary, not in the
    # response. Mapping here keeps both paths returning the same thing.
    res = (
        db.table("portal_messages")
        .select("id, firm_id, client_id, body, sender_type, created_at")
        .eq("firm_id", firm_id)
        .eq("client_id", client_id)
        .order("created_at", desc=True)
        .execute()
    )
    return api_response(True, [
        {
            "id": m["id"], "firm_id": m["firm_id"], "client_id": m["client_id"],
            "text": m.get("body"),
            "from_ca": m.get("sender_type") == "ca",
            "created_at": m.get("created_at"),
        }
        for m in (res.data or [])
    ])


@router.post("/messages")
def send_message(
    body: SendMessageBody,
    current_user: dict = Depends(rbac("portal", "write")),
):
    """Send a portal message from CA to client."""
    # M2 audit finding: client_id was caller-supplied and never checked.
    assert_client_access(current_user, body.client_id)
    firm_id = current_user["firm_id"]
    db = _db()
    if db is None:
        record = portal_svc.send_message(
            firm_id=firm_id,
            client_id=body.client_id,
            text=body.text,
            from_ca=body.from_ca,
        )
        return api_response(True, record)

    now = _now()
    # Same column mismatch as the read above, and the same 500: this INSERT
    # named `text` and `from_ca`, so no portal message has ever been written
    # through this endpoint. sender_type is CHECKed to ('ca','client').
    row = {
        "id": str(uuid.uuid4()),
        "firm_id": firm_id,
        "client_id": body.client_id,
        "body": body.text,
        "sender_type": "ca" if body.from_ca else "client",
        "created_at": now,
    }

    res = db.table("portal_messages").insert(row).execute()
    written = (res.data or [row])[0]
    # Answer in the shape callers expect (see the read path's note).
    return api_response(True, {
        "id": written["id"], "firm_id": written["firm_id"],
        "client_id": written["client_id"],
        "text": written.get("body"),
        "from_ca": written.get("sender_type") == "ca",
        "created_at": written.get("created_at"),
    })


# ── Dues ──────────────────────────────────────────────────────────────────────

@router.get("/dues")
def get_dues(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("portal", "read")),
):
    """
    Outstanding dues summary for a client (CA-facing).

    Phase 4.5.2: this now reads the CANONICAL accounts-receivable source — the
    firm's fee invoices issued to the client (resolved via the firm↔client
    customer link) — instead of the legacy `transactions` table, which is
    retired here. The portal client-facing equivalent is GET /api/portal/self/dues.
    All amounts are in integer paise — never float.
    """
    # M2 audit finding: client_id was caller-supplied and never checked.
    assert_client_access(current_user, client_id)
    firm_id = current_user["firm_id"]
    return api_response(True, portal_data_service.dues(firm_id, client_id, db=_db()))
