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
from core.authz import assert_client_access, can_access_client, effective_client_ids  # M2: assignment scope
import domain.portal_service as portal_svc
from services import portal_data_service  # Phase 4.5.2: canonical AR (retires `transactions` dues)
from services import portal_notice_service  # practice_management-02: tell both sides
from core import db_provider

router = APIRouter(prefix="/api/portal", tags=["portal"])

# ── Dual-path: use in-memory mock when SUPABASE_URL is not set ────────────────
_USE_MOCK = not os.environ.get("SUPABASE_URL")


def _db():
    return None if _USE_MOCK else db_provider.request_db()


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
        # `due_date` was NOT a column here for the whole life of this endpoint —
        # PostgREST rejects the whole select at parse time, so it returned 500 on
        # every call — and it was dropped from this read rather than invented to
        # satisfy a select nobody depended on. Migration 450 added it, because
        # POST (below) declared it all along and the mail the client now gets
        # says when the document is needed by; this read names it again.
        .select("id, firm_id, client_id, title, description, is_urgent, status, "
                "fulfilled_at, created_at, due_date")
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
        return api_response(True, {**record, "client_notice": portal_notice_service.document_requested(
            firm_id, body.client_id, record)})

    now = _now()
    record = {
        "id": str(uuid.uuid4()),
        "firm_id": firm_id,
        "client_id": body.client_id,
        "requested_by": current_user.get("id"),
        "title": body.title,
        "description": body.description,
        "due_date": body.due_date,
        "is_urgent": body.is_urgent,
        "status": "pending",
        "fulfilled_at": None,
        "created_at": now,
    }

    res = db.table("document_requests").insert(record).execute()
    written = res.data[0] if res.data else record
    # practice_management-02: tell the client's portal contacts. The request is
    # already saved, so this can never fail it, and the answer says whether the
    # client was told — "created" and "the client knows" are two facts.
    written = {**written, "client_notice": portal_notice_service.document_requested(
        firm_id, body.client_id, written)}
    return api_response(True, written)


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
        .select("id, firm_id, client_id, body, sender_type, is_read, created_at")
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
            # Whether the FIRM has opened it - meaningful for a message the
            # client sent; a CA message's flag is the client's to set.
            "is_read": bool(m.get("is_read")),
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
        if body.from_ca:
            record = {**record, "client_notice": portal_notice_service.ca_message_posted(
                firm_id, body.client_id)}
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
    out = {
        "id": written["id"], "firm_id": written["firm_id"],
        "client_id": written["client_id"],
        "text": written.get("body"),
        "from_ca": written.get("sender_type") == "ca",
        "created_at": written.get("created_at"),
    }
    # practice_management-02: a message FROM the practice reaches the client's
    # portal contacts by mail (the words stay on the portal). Only a CA message:
    # this door also lets the body name `from_ca: false`, and a mail telling
    # the client "your accountant wrote to you" about that would be a lie.
    if written.get("sender_type") == "ca":
        out["client_notice"] = portal_notice_service.ca_message_posted(firm_id, body.client_id)
    return api_response(True, out)


class MarkThreadReadBody(BaseModel):
    client_id: str


@router.get("/unread")
def unread_portal_messages(current_user: dict = Depends(rbac("portal", "read"))):
    """Client messages nobody at the firm has opened, per client - the firm-wide
    count, so staff do not have to open each client's tab to find out who wrote.
    Narrowed to the caller's own book (`effective_client_ids`: None is firm-wide,
    an empty set is nothing)."""
    return api_response(True, portal_notice_service.unread_summary(
        current_user["firm_id"], effective_client_ids(current_user)))


@router.post("/messages/read")
def mark_thread_read(body: MarkThreadReadBody,
                     current_user: dict = Depends(rbac("portal", "write"))):
    """The firm has opened this client's thread: mark what the client sent as
    read. Only `is_read` / `read_at` change, and only on the CLIENT's messages.

    `portal:write`, which is the tier that can answer the thread: a role that
    may only READ the messages sees the count and does not clear it for
    everybody else (the firm-wide flag is one per message, not one per reader),
    and `tests/test_write_requires_write_permission.py` is right that a route
    which changes a row is not satisfied by a read-level action."""
    assert_client_access(current_user, body.client_id)
    marked = portal_notice_service.mark_thread_read(current_user["firm_id"], body.client_id)
    return api_response(True, {"marked_read": marked})


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
