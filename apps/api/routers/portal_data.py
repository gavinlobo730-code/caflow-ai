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
