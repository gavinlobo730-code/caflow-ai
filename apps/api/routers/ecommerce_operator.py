"""What an e-commerce operator's sellers supplied through it (GST-25, GSTR-8).

WRITES ARE `gst.compute` (the tier every recording endpoint in
`routers/gst_workspace.py` — the ITC register reversal/reclaim, for instance —
already uses; there is no `gst.write` action), READS `gst.read`. Nothing here
transmits anything to any portal; `services.gst_return_service
.gstr8_statement` is the only reader that turns these rows into a statement.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.authz import assert_client_access
from core.permissions import rbac
from core.validators import validate_gstin
from models.common import api_response

router = APIRouter(prefix="/api/ecommerce-operator", tags=["ecommerce_operator"])


def _mock_enabled() -> bool:
    from core.config import settings as _s
    return bool(getattr(_s, "USE_MOCK_DATA", False))


class SupplyIn(BaseModel):
    """One registered seller's figures for a period — GSTR-8 Table 3.

    `gstin` is the OPERATOR's own registration this row is filed under
    (GST-20's multi-registration shape); omit it to mean the primary.
    """
    client_id: str
    gstin: Optional[str] = None
    period: str
    supplier_gstin: str
    place_of_supply: Optional[str] = None
    gross_registered_paise: int = 0
    returns_registered_paise: int = 0
    gross_unregistered_paise: int = 0
    returns_unregistered_paise: int = 0
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    notes: Optional[str] = None


class UnregisteredSupplyIn(BaseModel):
    """One Enrolment-ID seller's figures for a period — GSTR-8 Table 3.1."""
    client_id: str
    gstin: Optional[str] = None
    period: str
    enrolment_id: str
    gross_value_paise: int = 0
    returns_paise: int = 0
    notes: Optional[str] = None


@router.get("/supplies")
def list_supplies(
    client_id: str = Query(...),
    period: str = Query(..., pattern=r"^\d{6}$"),
    gstin: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("gst", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"registered": [], "unregistered": []})
    from core.supabase_client import get_supabase
    from services import client_gst_registration_service as regs
    from services import ecommerce_operator_service as eco_svc
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    try:
        registration = regs.resolve(db, firm_id, client_id, gstin)
    except HTTPException:
        raise
    return api_response(True, {
        "registered": eco_svc.list_supplies(db, firm_id, client_id,
                                            registration.gstin, period),
        "unregistered": eco_svc.list_unregistered_supplies(
            db, firm_id, client_id, registration.gstin, period),
    })


@router.post("/supplies")
def record_supply(
    data: SupplyIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, data.client_id)
    supplier_gstin = data.supplier_gstin.strip().upper()
    # §16(2)(aa)'s credit follows the GSTIN a return names, and a well-formed
    # WRONG one is worse than an obviously wrong one (GST-29's reasoning,
    # applied to the seller GSTR-8 names rather than a customer or vendor).
    err = validate_gstin(supplier_gstin)
    if err:
        raise HTTPException(status_code=422, detail=err)
    if _mock_enabled():
        return api_response(True, {"id": "mock-supply", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import client_gst_registration_service as regs
    from services import ecommerce_operator_service as eco_svc
    from services.audit_service import log_event
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = regs.resolve(db, firm_id, data.client_id, data.gstin)
    row = eco_svc.record_supply(
        db, firm_id, data.client_id, gstin=registration.gstin,
        period=data.period, supplier_gstin=supplier_gstin,
        place_of_supply=data.place_of_supply,
        gross_registered_paise=data.gross_registered_paise,
        returns_registered_paise=data.returns_registered_paise,
        gross_unregistered_paise=data.gross_unregistered_paise,
        returns_unregistered_paise=data.returns_unregistered_paise,
        igst_paise=data.igst_paise, cgst_paise=data.cgst_paise,
        sgst_paise=data.sgst_paise, notes=data.notes,
        actor_id=current_user.get("id"))
    log_event(firm_id or "", "ecommerce_operator_supply", row.get("id") or "",
              "record", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.delete("/supplies/{supply_id}")
def delete_supply(
    supply_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": supply_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services import ecommerce_operator_service as eco_svc
    from services.audit_service import log_event
    row = eco_svc.delete_supply(get_supabase(), current_user.get("firm_id"), supply_id)
    log_event(current_user.get("firm_id") or "", "ecommerce_operator_supply",
              supply_id, "delete", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": supply_id, "deleted": True})


@router.post("/unregistered-supplies")
def record_unregistered_supply(
    data: UnregisteredSupplyIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, data.client_id)
    if _mock_enabled():
        return api_response(True, {"id": "mock-unreg-supply", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import client_gst_registration_service as regs
    from services import ecommerce_operator_service as eco_svc
    from services.audit_service import log_event
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = regs.resolve(db, firm_id, data.client_id, data.gstin)
    row = eco_svc.record_unregistered_supply(
        db, firm_id, data.client_id, gstin=registration.gstin,
        period=data.period, enrolment_id=data.enrolment_id,
        gross_value_paise=data.gross_value_paise, returns_paise=data.returns_paise,
        notes=data.notes, actor_id=current_user.get("id"))
    log_event(firm_id or "", "ecommerce_operator_unregistered_supply",
              row.get("id") or "", "record",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.delete("/unregistered-supplies/{supply_id}")
def delete_unregistered_supply(
    supply_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": supply_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services import ecommerce_operator_service as eco_svc
    from services.audit_service import log_event
    row = eco_svc.delete_unregistered_supply(get_supabase(),
                                             current_user.get("firm_id"), supply_id)
    log_event(current_user.get("firm_id") or "",
              "ecommerce_operator_unregistered_supply", supply_id, "delete",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": supply_id, "deleted": True})
