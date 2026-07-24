"""
E-Way Bill Integration — CGST Act Section 68, Rule 138.
# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to NIC portal
"""
from __future__ import annotations
import logging
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from core.permissions import rbac
from core.authz import assert_client_access
from models.common import api_response
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/eway-bill", tags=["eway_bill"])
_logger = logging.getLogger("caflow.eway_bill.router")


class CreateEWayBillRequest(BaseModel):
    client_id: str
    invoice_number: str
    dispatch_from: str
    ship_to: str
    goods_description: str
    taxable_value_paise: int = Field(..., ge=0)
    sales_invoice_id: Optional[str] = None
    hsn_code: Optional[str] = None
    vehicle_number: Optional[str] = None
    vehicle_type: Optional[str] = None
    transport_mode: Optional[str] = None
    distance_km: Optional[int] = None
    transporter_id: Optional[str] = None
    transporter_name: Optional[str] = None
    provider: str = "manual"


class RecordEWBGeneratedRequest(BaseModel):
    ewb_number: str
    ewb_date: str
    ewb_valid_upto: str
    provider_response: Optional[dict] = None


class ExtendEWBRequest(BaseModel):
    new_valid_upto: str
    extension_reason: str


class CancelEWBRequest(BaseModel):
    cancellation_reason: str


@router.post("/records")
def create_eway_bill(
    req: CreateEWayBillRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, req.client_id)
    from domain.income_tax.eway_service import create_eway_bill as _create
    try:
        rec = _create(
            firm_id=current_user["firm_id"],
            client_id=req.client_id,
            invoice_number=req.invoice_number,
            dispatch_from=req.dispatch_from,
            ship_to=req.ship_to,
            goods_description=req.goods_description,
            taxable_value_paise=req.taxable_value_paise,
            created_by=current_user["id"],
            sales_invoice_id=req.sales_invoice_id,
            hsn_code=req.hsn_code,
            vehicle_number=req.vehicle_number,
            vehicle_type=req.vehicle_type,
            transport_mode=req.transport_mode,
            distance_km=req.distance_km,
            transporter_id=req.transporter_id,
            transporter_name=req.transporter_name,
            provider=req.provider,
        )
        return api_response(True, {**rec, "ca_review_required": True})
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.get("/records")
def list_eway_bills(
    client_id: str,
    status: Optional[str] = None,
    current_user: dict = Depends(rbac("gst", "read")),
):
    from domain.income_tax.eway_service import list_eway_bills as _list
    return api_response(True, _list(current_user["firm_id"], client_id, status))


@router.post("/records/{record_id}/generated")
def record_ewb_generated(
    record_id: str,
    req: RecordEWBGeneratedRequest,
    current_user: dict = Depends(rbac("gst", "approve")),
):
    """# CA REVIEW REQUIRED — Record EWB generated on NIC portal."""
    from domain.income_tax.eway_service import record_ewb_generated as _record
    try:
        result = _record(
            firm_id=current_user["firm_id"],
            record_id=record_id,
            ewb_number=req.ewb_number,
            ewb_date=req.ewb_date,
            ewb_valid_upto=req.ewb_valid_upto,
            provider_response=req.provider_response,
        )
        # Bug fix (Batch 7): timeline_service.log takes title/…, not action/
        # metadata (the old call raised TypeError → 500). Logged at client level;
        # the invoice Hub derives compliance activity from the records to avoid a
        # duplicate entry, so we do NOT entity-scope here (Batch 8 fix).
        timeline_service.log(
            client_id=result.get("client_id", ""),
            firm_id=current_user["firm_id"],
            category="tax",
            title="E-Way Bill generated",
            description=f"E-Way Bill {req.ewb_number} (valid to {req.ewb_valid_upto})",
            severity="success",
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/records/{record_id}/extend")
def extend_ewb(
    record_id: str,
    req: ExtendEWBRequest,
    current_user: dict = Depends(rbac("gst", "approve")),
):
    from domain.income_tax.eway_service import record_ewb_extended
    try:
        result = record_ewb_extended(
            current_user["firm_id"], record_id, req.new_valid_upto, req.extension_reason
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@router.post("/records/{record_id}/cancel")
def cancel_ewb(
    record_id: str,
    req: CancelEWBRequest,
    current_user: dict = Depends(rbac("gst", "approve")),
):
    """# CA REVIEW REQUIRED — Cancel EWB on NIC portal first."""
    from domain.income_tax.eway_service import record_ewb_cancelled
    try:
        result = record_ewb_cancelled(
            current_user["firm_id"], record_id, req.cancellation_reason
        )
        timeline_service.log(
            client_id=result.get("client_id", ""),
            firm_id=current_user["firm_id"],
            category="tax",
            title="E-Way Bill cancelled",
            description=f"E-Way Bill cancelled: {req.cancellation_reason}",
            severity="warning",
        )
        return api_response(True, result)
    except Exception as e:
        raise HTTPException(500, detail=str(e))
