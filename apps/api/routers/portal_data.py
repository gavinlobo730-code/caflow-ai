"""
Portal Data Surfaces router (Phase 4.5.2) — CLIENT-facing, read-only.

Authenticated via get_current_portal_client (the client's own Supabase JWT →
active portal-client context; NO staff privilege). Every endpoint is scoped to
the caller's ACTIVE client and exposes ONLY the firm↔client fee relationship
(invoices the firm issued to the client, canonical dues, statements, payment
reminders) plus the client's own compliance status — never the client's own
accounting ledger, journals, or internal working papers.

Prefix /api/portal/self keeps these distinct from the staff /api/portal/* CA
endpoints. Registered in main.py WITHOUT the staff _CLIENT_GUARD (it uses its
own portal auth), exactly like portal_self / portal_access.

All monetary values are integer paise — never float.
"""
import os
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from models.common import api_response
from core.portal_auth import get_current_portal_client
from services import portal_data_service

router = APIRouter(prefix="/api/portal/self", tags=["portal_data"])

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.portal_data_router")


# ── Invoices + Canonical Dues ─────────────────────────────────────────────────

@router.get("/invoices")
def portal_invoices(portal: dict = Depends(get_current_portal_client)):
    """Fee invoices the firm issued to THIS client (client-safe projection)."""
    rows = portal_data_service.list_invoices(portal["firm_id"], portal["client_id"])
    return api_response(True, {"invoices": rows})


@router.get("/invoices/{invoice_id}/pdf")
def portal_invoice_pdf(invoice_id: str, portal: dict = Depends(get_current_portal_client)):
    """Download a fee invoice PDF. Ownership-gated: the invoice MUST be a fee
    invoice issued to this portal client, else 404 (never reveal existence)."""
    # Ownership gate FIRST — a client may only ever fetch their own fee invoices.
    if not portal_data_service.invoice_in_scope(portal["firm_id"], portal["client_id"], invoice_id):
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if _USE_MOCK:
        raise HTTPException(status_code=501, detail="PDF not available in mock mode")
    from services.invoice_pdf_service import get_sales_invoice_pdf
    try:
        pdf_bytes, filename = get_sales_invoice_pdf(invoice_id, portal["firm_id"])
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        _logger.error("portal_invoice_pdf %s: %s", invoice_id, e)
        raise HTTPException(status_code=500, detail="PDF generation failed")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/invoices/{invoice_id}/pay")
def portal_pay_invoice(invoice_id: str, portal: dict = Depends(get_current_portal_client)):
    """Pay Now (Phase 4.6): create or reuse a payment link for the client's OWN
    invoice and return the hosted checkout URL. Ownership-gated (same gate as the
    PDF); exposes NO accounting data — only the amount due and the pay URL."""
    firm_id, client_id = portal["firm_id"], portal["client_id"]
    if not portal_data_service.invoice_in_scope(firm_id, client_id, invoice_id):
        raise HTTPException(status_code=404, detail="Invoice not found.")
    if _USE_MOCK:
        raise HTTPException(status_code=501, detail="Online payments not available in mock mode")
    from core.supabase_client import get_supabase
    from services import payment_service
    link = payment_service.create_link(
        get_supabase(), firm_id, invoice_id,
        actor={"auth_user_id": None, "email": portal.get("email")})
    return api_response(True, {"short_url": link.get("short_url"),
                              "amount_paise": link.get("amount_paise"), "status": link.get("status")})


@router.get("/dues")
def portal_dues(portal: dict = Depends(get_current_portal_client)):
    """Canonical AR: outstanding fee invoices the client owes the firm (integer paise)."""
    return api_response(True, portal_data_service.dues(portal["firm_id"], portal["client_id"]))


# ── Statements + Reminder History ─────────────────────────────────────────────

@router.get("/statement")
def portal_statement(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    portal: dict = Depends(get_current_portal_client),
):
    """Account statement of the firm↔client fee relationship. Defaults to the
    current Indian financial year (Apr 1 – Mar 31) when no window is given."""
    if not start or not end:
        start, end = portal_data_service.current_fy_range()
    data = portal_data_service.statement(portal["firm_id"], portal["client_id"], start, end)
    return api_response(True, data)


@router.get("/statement/pdf")
def portal_statement_pdf(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    portal: dict = Depends(get_current_portal_client),
):
    """Download the fee-relationship statement PDF (scoped to this client)."""
    if not start or not end:
        start, end = portal_data_service.current_fy_range()
    if _USE_MOCK:
        raise HTTPException(status_code=501, detail="PDF not available in mock mode")
    try:
        pdf_bytes, filename = portal_data_service.statement_pdf(
            portal["firm_id"], portal["client_id"], start, end)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("portal_statement_pdf %s/%s: %s", portal["firm_id"], portal["client_id"], e)
        raise HTTPException(status_code=500, detail="PDF generation failed")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/reminders")
def portal_reminders(portal: dict = Depends(get_current_portal_client)):
    """Payment-reminder history for this client's fee invoices (client-safe)."""
    rows = portal_data_service.reminder_history(portal["firm_id"], portal["client_id"])
    return api_response(True, {"reminders": rows})


# ── Compliance Status ─────────────────────────────────────────────────────────

@router.get("/compliance")
def portal_compliance(portal: dict = Depends(get_current_portal_client)):
    """This client's compliance obligation status (client-safe; no internal notes,
    assignees, risk, or escalation)."""
    rows = portal_data_service.compliance(portal["firm_id"], portal["client_id"])
    return api_response(True, {"compliance": rows})


# ── Documents, requests and messages ──────────────────────────────────────────
#
# `portal_self._DASHBOARD_SECTIONS` has advertised these three as
# `available: True` since it was written and NOTHING served them; the dashboard
# filtered all three out of its own tab row with a browser-side
# `DATA_SECTIONS` set, so the API told a client they existed and the screen
# quietly disagreed. The `capital_wip` shape on the one surface the outside
# world sees, and the worse half is that the API was the one making the claim.
#
# Served here rather than read over PostgREST although migration 109's policies
# allow it — `portal_data_service`'s own header records why, and the short
# version is that the DOWNLOAD cannot work from the browser at all: migration
# 005's storage policies gate the bucket on `get_my_firm_id()`, which reads the
# staff `users` table a portal contact has no row in.

class PortalMessageBody(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)


@router.get("/documents")
def portal_documents(portal: dict = Depends(get_current_portal_client)):
    """Documents the firm has filed against THIS client."""
    rows = portal_data_service.list_documents(portal["firm_id"], portal["client_id"])
    return api_response(True, {"documents": rows})


@router.get("/documents/{document_id}/download")
def portal_document_download(document_id: str,
                             portal: dict = Depends(get_current_portal_client)):
    """Download one document. Ownership-gated FIRST, then a short-lived signed
    URL minted with the service role — the same shape `/invoices/{id}/pdf`
    takes for this principal, and for the same reason.

    404 rather than 403 on a document belonging to another client: never reveal
    that it exists.

    A SIGNED URL IS RETURNED, NOT THE BYTES — and not a 302 either, because
    every other endpoint here answers the `{success, data, error}` envelope and
    one that redirects instead would need its own handling in the browser.
    Streaming the file through Render in Singapore would put a Mumbai round
    trip and the whole file in front of every download; a 60-second signed URL
    lets the browser fetch it from storage directly. Sixty seconds because the
    link is followed immediately and a longer one is a bearer token for the
    file — the same argument `domain/attachments` records for never STORING a
    signed url."""
    doc = portal_data_service.document_in_scope(
        portal["firm_id"], portal["client_id"], document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")
    if _USE_MOCK:
        raise HTTPException(status_code=501, detail="Download not available in mock mode")

    from core.supabase_client import get_supabase
    try:
        signed = get_supabase().storage.from_("Documents").create_signed_url(
            doc["file_path"], 60)
    except Exception as e:
        _logger.error("portal_document_download %s: %s", document_id, e)
        raise HTTPException(status_code=500, detail="Could not prepare the download.")
    url = (signed or {}).get("signedURL") or (signed or {}).get("signedUrl")
    if not url:
        raise HTTPException(status_code=500, detail="Could not prepare the download.")
    return api_response(True, {"url": url, "file_name": doc.get("file_name")})


@router.get("/document-requests")
def portal_document_requests(portal: dict = Depends(get_current_portal_client)):
    """What the firm has asked this client for. Open first, urgent before the
    rest, oldest before newest — the reverse of every other list here, because
    the request that has been waiting longest is the one holding work up.

    READ-ONLY, AND THE UPLOAD IS DELIBERATELY NOT BUILT. Fulfilling a request
    means writing a file into the firm's own document store, and migration
    005's storage policies admit no portal principal; granting one is a
    decision about quota, scanning and what lands in a CA's audit file rather
    than a missing endpoint. Named on the screen so a client is told where to
    send the papers instead of being shown a button that fails."""
    rows = portal_data_service.list_document_requests(
        portal["firm_id"], portal["client_id"])
    return api_response(True, {"requests": rows})


@router.get("/messages")
def portal_messages(portal: dict = Depends(get_current_portal_client)):
    """The thread between the firm and this client, oldest first."""
    rows = portal_data_service.list_messages(portal["firm_id"], portal["client_id"])
    return api_response(True, {"messages": rows})


@router.post("/messages")
def portal_post_message(body: PortalMessageBody,
                        portal: dict = Depends(get_current_portal_client)):
    """Send a message to the firm.

    `sender_type` is stamped 'client' in the service and is never taken from
    the request — migration 048 CHECKs it to ('ca', 'client'), so a
    caller-supplied value would let a client post a message that reads as
    their accountant's."""
    row = portal_data_service.post_message(
        portal["firm_id"], portal["client_id"],
        body.body.strip(), portal.get("name"))
    return api_response(True, {"message": row})
