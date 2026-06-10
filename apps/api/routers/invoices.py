"""
Invoice management endpoints.

All endpoints require RBAC: invoice.read/write

Endpoints:
  GET    /api/invoices                           - list invoices (with filters)
  GET    /api/invoices/{invoice_id}              - get one invoice
  POST   /api/invoices/from-engagement/{id}      - generate from fixed fee
  POST   /api/invoices/from-time/{id}            - generate from time entries
  PATCH  /api/invoices/{invoice_id}/status       - transition status
  DELETE /api/invoices/{invoice_id}              - delete (Draft only)
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from models.common import api_response
from core.permissions import rbac
from repositories.invoice_repository import invoice_repo
from core.exceptions import NotFoundError
from services.audit_service import log_event

router = APIRouter(prefix="/api/invoices", tags=["invoices"])


class InvoiceListQuery(BaseModel):
    engagement_id: Optional[str] = None
    client_id: Optional[str] = None
    status: Optional[str] = None
    date_from: Optional[str] = None
    date_to: Optional[str] = None


class GenerateFromTimeQuery(BaseModel):
    invoice_month: Optional[str] = None
    billable_only: bool = True


class StatusChangeRequest(BaseModel):
    new_status: str = Field(..., description="New status: Draft, Issued, Paid, or Overdue")


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/invoices — List invoices with optional filters
# ─────────────────────────────────────────────────────────────────────────────

@router.get("")
def list_invoices(
    engagement_id: Optional[str] = Query(None),
    client_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("invoice", "read")),
):
    """
    List invoices with optional filters.

    Query parameters:
      - engagement_id: Filter by engagement
      - client_id: Filter by client
      - status: Filter by status (Draft, Issued, Paid, Overdue)
      - date_from: Filter from date (ISO format)
      - date_to: Filter to date (ISO format)
    """
    firm_id = current_user.get("firm_id")

    invoices = invoice_repo.find_all(
        firm_id=firm_id,
        engagement_id=engagement_id,
        client_id=client_id,
        status=status,
        date_from=date_from,
        date_to=date_to,
    )

    return api_response(True, {
        "invoices": invoices,
        "total": len(invoices),
    })


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/invoices/{invoice_id} — Get single invoice
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{invoice_id}")
def get_invoice(
    invoice_id: str,
    current_user: dict = Depends(rbac("invoice", "read")),
):
    """Fetch a single invoice by ID."""
    firm_id = current_user.get("firm_id")

    try:
        invoice = invoice_repo.find_by_id_or_raise(invoice_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.get("firm_id") != firm_id:
        raise HTTPException(status_code=403, detail="Access denied")

    return api_response(True, {"invoice": invoice})


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/invoices/from-engagement/{engagement_id} — Generate from fixed fee
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/from-engagement/{engagement_id}")
def generate_from_engagement(
    engagement_id: str,
    invoice_month: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """
    Generate a draft invoice from a fixed-fee engagement.

    The invoice amount is taken from engagement.fee_paise, with 18% GST added.

    Query parameters:
      - invoice_month: Optional invoice date (ISO format, defaults to today)
    """
    from repositories.engagement_repository import engagement_repo
    from services.invoice_generation_service import generate_invoice_from_engagement

    firm_id = current_user.get("firm_id")

    # Verify engagement exists and belongs to firm
    try:
        engagement = engagement_repo.get_or_raise(engagement_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Engagement not found")

    if engagement.get("firm_id") != firm_id:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        invoice_id = generate_invoice_from_engagement(engagement_id, invoice_month)
        invoice = invoice_repo.find_by_id(invoice_id)
        return api_response(True, {"invoice": invoice})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/invoices/from-time/{engagement_id} — Generate from time entries
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/from-time/{engagement_id}")
def generate_from_time_entries(
    engagement_id: str,
    invoice_month: Optional[str] = Query(None),
    billable_only: bool = Query(True),
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """
    Generate a draft invoice from time entries.

    Queries time_entries for the engagement in the specified month and
    calculates invoice amount based on hourly rates.

    Query parameters:
      - invoice_month: Optional invoice date (ISO format, defaults to today)
      - billable_only: Include only billable time entries (default: true)
    """
    from repositories.engagement_repository import engagement_repo
    from services.invoice_generation_service import generate_invoice_from_time_entries

    firm_id = current_user.get("firm_id")

    # Verify engagement exists and belongs to firm
    try:
        engagement = engagement_repo.get_or_raise(engagement_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Engagement not found")

    if engagement.get("firm_id") != firm_id:
        raise HTTPException(status_code=403, detail="Access denied")

    try:
        invoice_id = generate_invoice_from_time_entries(
            engagement_id,
            invoice_month,
            billable_only,
        )
        invoice = invoice_repo.find_by_id(invoice_id)
        return api_response(True, {"invoice": invoice})
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


# ─────────────────────────────────────────────────────────────────────────────
# GET /api/invoices/{invoice_id}/pdf — Download GST tax invoice PDF
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{invoice_id}/pdf")
def download_invoice_pdf(
    invoice_id: str,
    current_user: dict = Depends(rbac("invoice", "read")),
):
    """
    Render and download the GST-compliant tax invoice PDF.
    Includes firm details, client details, SAC code and CGST/SGST/IGST breakdown.
    """
    from fastapi.responses import Response
    from services.invoice_pdf_service import get_invoice_pdf

    firm_id = current_user.get("firm_id")

    try:
        invoice = invoice_repo.find_by_id_or_raise(invoice_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.get("firm_id") != firm_id:
        raise HTTPException(status_code=403, detail="Access denied")

    pdf_bytes, filename = get_invoice_pdf(invoice_id)
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# POST /api/invoices/run-overdue-check — Transition Issued past due to Overdue
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/run-overdue-check")
def run_overdue_check_endpoint(
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """
    Run the invoice lifecycle check for this firm: any Issued invoice past
    its due date (invoice_date + 30 days if no explicit due_date) is marked
    Overdue. Also runs automatically via the daily scheduler.
    """
    from services.invoice_lifecycle_service import run_overdue_check

    firm_id = current_user.get("firm_id")
    result = run_overdue_check(firm_id=firm_id)
    return api_response(True, result)


# ─────────────────────────────────────────────────────────────────────────────
# PATCH /api/invoices/{invoice_id}/status — Transition status
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/{invoice_id}/status")
def change_invoice_status(
    invoice_id: str,
    body: StatusChangeRequest,
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """
    Transition invoice status: Draft → Issued → Paid → Overdue

    Request body:
      - new_status: One of 'Draft', 'Issued', 'Paid', 'Overdue'
    """
    firm_id = current_user.get("firm_id")

    # Verify invoice exists and belongs to firm
    try:
        invoice = invoice_repo.find_by_id_or_raise(invoice_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.get("firm_id") != firm_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Validate new_status
    valid_statuses = {"Draft", "Issued", "Paid", "Overdue"}
    if body.new_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}",
        )

    updated = invoice_repo.change_status(invoice_id, body.new_status)
    log_event(firm_id, "invoice", invoice_id, "status_change",
              actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
              old_data={"status": invoice.get("status")}, new_data={"status": body.new_status})
    return api_response(True, {"invoice": updated})


# ─────────────────────────────────────────────────────────────────────────────
# DELETE /api/invoices/{invoice_id} — Delete invoice (Draft only)
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/{invoice_id}")
def delete_invoice(
    invoice_id: str,
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """
    Delete an invoice. Only Draft invoices can be deleted.

    Raises 400 if invoice is not in Draft status.
    """
    firm_id = current_user.get("firm_id")

    # Verify invoice exists and belongs to firm
    try:
        invoice = invoice_repo.find_by_id_or_raise(invoice_id)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Invoice not found")

    if invoice.get("firm_id") != firm_id:
        raise HTTPException(status_code=403, detail="Access denied")

    # Only Draft invoices can be deleted
    if invoice.get("status") != "Draft":
        raise HTTPException(
            status_code=400,
            detail=f"Cannot delete invoice with status '{invoice.get('status')}'. Only Draft invoices can be deleted.",
        )

    invoice_repo.delete(invoice_id)
    return api_response(True, {"deleted": True})
