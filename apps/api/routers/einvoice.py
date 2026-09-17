"""
E-Invoice Integration — IRN generation, cancellation, status.
CGST Act Section 31B, Rule 48(4) — E-Invoice mandate.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to IRP
#
# TODO(compliance): docs/compliance/02-gst.md
#   These routes RECORD an IRN a human obtained from an IRP; they do not
#   generate one. e-invoicing is the ONE place where the GSP gate does not
#   apply: NIC's sandbox at einv-apisandbox.nic.in is self-service with any
#   GSTIN, so rails could be built and tested before any commercial
#   conversation. Direct production API access is for turnover above Rs 500
#   crore; Rs 100-500 crore is GSP-only. Note the 30-day reporting limit for
#   AATO >= Rs 10 crore (from 01-04-2025) — it is an IRP VALIDATION, not
#   advice, and it applies to credit and debit notes too.
"""
from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client
from models.common import api_response
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/einvoice", tags=["einvoice"])
_logger = logging.getLogger("caflow.einvoice.router")


def _assert_record_scope(record_id: str, current_user: dict) -> dict:
    """Resolve record_id to its row inside the caller's firm AND assigned book.

    The two IRN routes below are row-addressed: the mount-level guard only
    fires on a client_id in the path/query/JSON body, and neither request
    carries one, so both previously scoped on firm_id alone — any member of
    the firm could mark an IRN generated against, or cancel the e-invoice of,
    another staff member's client. ONE fixed message covers missing,
    wrong-firm and unassigned alike, so the response is not an existence
    oracle.

    Callers MUST invoke this OUTSIDE their `try`: both handlers wrap the
    service call in `except Exception -> HTTPException(500)`, which would
    otherwise catch this 404 (HTTPException is an Exception) and re-raise it
    as a 500, turning a denial into a server error.
    """
    from domain.income_tax.einvoice_service import get_einvoice_record
    record = get_einvoice_record(current_user["firm_id"], record_id)
    if not record:
        raise HTTPException(status_code=404, detail="E-invoice record not found")
    if not can_access_client(current_user, record.get("client_id")):
        raise HTTPException(status_code=404, detail="E-invoice record not found")
    return record


_GST_TREATMENTS = {
    "regular", "export_with_payment", "export_without_payment",
    "sez_with_payment", "sez_without_payment", "deemed_export",
}


class CreateEInvoiceRequest(BaseModel):
    client_id: str
    invoice_number: str
    invoice_date: str  # YYYY-MM-DD
    sales_invoice_id: Optional[str] = None
    provider: str = "manual"
    # Compliance treatment captured for the IRN (metadata only — never used in
    # any tax/journal computation). LUT/Bond ref applies to without-payment.
    gst_treatment: Optional[str] = None
    lut_number: Optional[str] = None

    @field_validator("gst_treatment")
    @classmethod
    def _valid_treatment(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and v not in _GST_TREATMENTS:
            raise ValueError(f"Invalid gst_treatment '{v}'.")
        return v


class RecordIRNRequest(BaseModel):
    irn: str
    ack_number: str
    ack_date: str
    qr_data: Optional[str] = None
    provider_response: Optional[dict] = None


class CancelIRNRequest(BaseModel):
    cancellation_reason: str


def _invoice_treatment(firm_id: str, client_id: str, sales_invoice_id: Optional[str]) -> Optional[str]:
    """The treatment of the invoice this record NAMES, or None where it names
    none this product holds (SALES-19).

    `sales_invoice_id` is optional on the request — a record may be prepared for
    an invoice raised outside the product — so None is a real answer and not a
    failure. The read is scoped to the firm AND the client for the ordinary
    reason: a record must not be able to reach another book's invoice to borrow
    a treatment from it.
    """
    if not sales_invoice_id:
        return None
    from domain.gst.treatment import treatment_for_invoice

    def _of(inv: dict) -> str:
        return treatment_for_invoice(
            supply_type=inv.get("supply_type"),
            invoice_type=inv.get("invoice_type"),
            igst_paise=int(inv.get("igst_paise") or 0),
        )

    try:
        from routers.sales_invoices import _USE_MOCK as _SALES_MOCK, MOCK_SALES_INVOICES
        if _SALES_MOCK:
            inv = next(
                (i for i in MOCK_SALES_INVOICES
                 if i.get("id") == sales_invoice_id
                 and i.get("firm_id") == firm_id
                 and i.get("client_id") == client_id),
                None,
            )
            return _of(inv) if inv else None

        from core.supabase_client import get_supabase
        rows = (
            get_supabase().table("client_sales_invoices")
            .select("supply_type, invoice_type, igst_paise")
            .eq("id", sales_invoice_id)
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .is_("deleted_at", None)
            .limit(1)
            .execute().data
        ) or []
        return _of(rows[0]) if rows else None
    except Exception:
        # An unreadable invoice must not stop a record being prepared: the
        # caller's own value then stands, exactly as it did before this check.
        _logger.warning("Could not read invoice %s to derive its GST treatment", sales_invoice_id)
        return None


@router.post("/records")
def create_record(
    req: CreateEInvoiceRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Create e-invoice record in draft state."""
    assert_client_access(current_user, req.client_id)
    # ONE SUPPLY CANNOT BE DECLARED TWO WAYS (SALES-19). The invoice already
    # settles its own treatment through `supply_type` + `invoice_type` — the
    # fields GSTR-1 is built from — and this endpoint used to store whatever the
    # caller typed beside it, so a record could contradict its own invoice and
    # the compliance panel rendered both labels at once. The rule is
    # `domain/gst/treatment.treatment_for_record`; this is a 422 rather than a
    # 500 because the request is wrong, not the server.
    from domain.gst.treatment import treatment_for_record
    treatment, refusal = treatment_for_record(
        stated=req.gst_treatment,
        derived=_invoice_treatment(current_user["firm_id"], req.client_id, req.sales_invoice_id),
    )
    if refusal:
        raise HTTPException(422, detail=refusal)

    from domain.income_tax.einvoice_service import create_einvoice_record
    try:
        rec = create_einvoice_record(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            invoice_number=req.invoice_number,
            invoice_date=req.invoice_date,
            created_by=current_user["id"],
            sales_invoice_id=req.sales_invoice_id,
            provider=req.provider,
            gst_treatment=treatment,
            lut_number=req.lut_number,
        )
        return api_response(True, {**rec, "ca_review_required": True})
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/records")
def list_records(
    client_id: str,
    status: Optional[str] = None,
    current_user: dict = Depends(rbac("gst", "read")),
):
    from domain.income_tax.einvoice_service import list_einvoices
    # client_id is a required query param, so main.py's mount-level guard
    # already fired; explicit so the scope check is visible at the read.
    assert_client_access(current_user, client_id)
    return api_response(True, list_einvoices(current_user["firm_id"], client_id, status))


@router.post("/records/{record_id}/irn-generated")
def record_irn_generated(
    record_id: str,
    req: RecordIRNRequest,
    current_user: dict = Depends(rbac("gst", "approve")),
):
    """
    Record IRN generated by CA on IRP portal.
    # CA REVIEW REQUIRED — CA must generate IRN manually on https://einvoice1.gst.gov.in
    """
    # Outside the try on purpose — see _assert_record_scope.
    _assert_record_scope(record_id, current_user)
    from domain.income_tax.einvoice_service import record_irn_generated as _record
    try:
        result = _record(
            firm_id=current_user["firm_id"],
            record_id=record_id,
            irn=req.irn,
            ack_number=req.ack_number,
            ack_date=req.ack_date,
            qr_data=req.qr_data,
            provider_response=req.provider_response,
        )
        # Bug fix (Batch 7): timeline_service.log takes title/…, not action/
        # metadata — the old call raised TypeError → 500. Logged at client level;
        # the invoice Hub derives compliance activity from the records themselves
        # (compliance.complianceTimelineItems) so we do NOT entity-scope here —
        # that would double-list the event in the Hub timeline (Batch 8 fix).
        timeline_service.log(
            client_id=result.get("client_id", ""),
            firm_id=current_user["firm_id"],
            category="tax",
            title="E-Invoice IRN generated",
            description=f"IRN {req.irn} (ACK {req.ack_number})",
            severity="success",
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/records/{record_id}/cancel")
def cancel_irn(
    record_id: str,
    req: CancelIRNRequest,
    current_user: dict = Depends(rbac("gst", "approve")),
):
    """
    Record IRN cancellation.
    # CA REVIEW REQUIRED — Cancellation must be done on IRP portal first
    """
    # Outside the try on purpose — see _assert_record_scope.
    _assert_record_scope(record_id, current_user)
    from domain.income_tax.einvoice_service import record_irn_cancelled
    try:
        result = record_irn_cancelled(
            firm_id=current_user["firm_id"],
            record_id=record_id,
            cancellation_reason=req.cancellation_reason,
        )
        timeline_service.log(
            client_id=result.get("client_id", ""),
            firm_id=current_user["firm_id"],
            category="tax",
            title="E-Invoice cancelled",
            description=f"IRN cancelled: {req.cancellation_reason}",
            severity="warning",
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))
