"""A composition dealer's inward supplies for the year (GST-25, GSTR-4 Annual).

Same tier split as `routers/ecommerce_operator.py`: WRITES are `gst.compute`
(there is no `gst.write` action), READS are `gst.read`. Nothing here transmits
anything to any portal; `services.gstr4_annual_service.gstr4_annual_statement`
is the only reader that turns these rows into a statement.
"""
from __future__ import annotations

from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from core.authz import assert_client_access
from core.permissions import rbac
from core.validators import validate_gstin, validate_pan, validate_state_code
from models.common import api_response
from models.fy import FYLabel

router = APIRouter(prefix="/api/gstr4-annual", tags=["gstr4_annual"])


def _mock_enabled() -> bool:
    from core.config import settings as _s
    return bool(getattr(_s, "USE_MOCK_DATA", False))


def _check_state(place_of_supply: str) -> None:
    err = validate_state_code(place_of_supply)
    if err:
        raise HTTPException(status_code=422, detail=err)


class B2BSupplyIn(BaseModel):
    """One registered supplier's line — Table 4A or 4B, same shape.

    `gstin` is the composition dealer's OWN registration this row is filed
    under (GST-20's multi-registration shape); omit it to mean the primary.
    """
    client_id: str
    gstin: Optional[str] = None
    financial_year: FYLabel
    supplier_gstin: str
    place_of_supply: str
    rate_bps: int = 0
    taxable_value_paise: int = 0
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0
    notes: Optional[str] = None


class UrpSupplyIn(BaseModel):
    """One unregistered supplier's line — Table 4C."""
    client_id: str
    gstin: Optional[str] = None
    financial_year: FYLabel
    counterparty_pan: Optional[str] = None
    reverse_charge: bool = False
    place_of_supply: str
    supply_type: Optional[str] = None
    rate_bps: Optional[int] = None
    taxable_value_paise: int = 0
    igst_paise: int = 0
    cgst_paise: int = 0
    sgst_paise: int = 0
    cess_paise: int = 0
    notes: Optional[str] = None


class ImportOfServiceIn(BaseModel):
    """One rate line — Table 4D. No CGST/SGST field at all — see
    migration 422's own note (IGST Act s.7(4))."""
    client_id: str
    gstin: Optional[str] = None
    financial_year: FYLabel
    place_of_supply: str
    rate_bps: int = 0
    taxable_value_paise: int = 0
    igst_paise: int = 0
    cess_paise: int = 0
    notes: Optional[str] = None


def _resolve(db, firm_id, client_id, gstin):
    from services import client_gst_registration_service as regs
    return regs.resolve(db, firm_id, client_id, gstin)


@router.get("/b2b-supplies")
def list_b2b_supplies(
    client_id: str = Query(...),
    financial_year: Annotated[FYLabel, Query(...)] = ...,
    gstin: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("gst", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, [])
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = _resolve(db, firm_id, client_id, gstin)
    return api_response(True, svc.list_b2b_supplies(
        db, firm_id, client_id, registration.gstin, financial_year))


@router.post("/b2b-supplies")
def record_b2b_supply(
    data: B2BSupplyIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, data.client_id)
    supplier_gstin = data.supplier_gstin.strip().upper()
    err = validate_gstin(supplier_gstin)
    if err:
        raise HTTPException(status_code=422, detail=err)
    _check_state(data.place_of_supply)
    if _mock_enabled():
        return api_response(True, {"id": "mock-b2b-supply", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    from services.audit_service import log_event
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = _resolve(db, firm_id, data.client_id, data.gstin)
    row = svc.record_b2b_supply(
        db, firm_id, data.client_id, gstin=registration.gstin,
        financial_year=data.financial_year, supplier_gstin=supplier_gstin,
        place_of_supply=data.place_of_supply, rate_bps=data.rate_bps,
        taxable_value_paise=data.taxable_value_paise,
        igst_paise=data.igst_paise, cgst_paise=data.cgst_paise,
        sgst_paise=data.sgst_paise, cess_paise=data.cess_paise,
        notes=data.notes, actor_id=current_user.get("id"))
    log_event(firm_id or "", "gstr4_annual_b2b_supply", row.get("id") or "",
              "record", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.delete("/b2b-supplies/{supply_id}")
def delete_b2b_supply(
    supply_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": supply_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    from services.audit_service import log_event
    row = svc.delete_b2b_supply(get_supabase(), current_user.get("firm_id"), supply_id)
    log_event(current_user.get("firm_id") or "", "gstr4_annual_b2b_supply",
              supply_id, "delete", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": supply_id, "deleted": True})


@router.get("/b2b-rc-supplies")
def list_b2b_rc_supplies(
    client_id: str = Query(...),
    financial_year: Annotated[FYLabel, Query(...)] = ...,
    gstin: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("gst", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, [])
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = _resolve(db, firm_id, client_id, gstin)
    return api_response(True, svc.list_b2b_rc_supplies(
        db, firm_id, client_id, registration.gstin, financial_year))


@router.post("/b2b-rc-supplies")
def record_b2b_rc_supply(
    data: B2BSupplyIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, data.client_id)
    supplier_gstin = data.supplier_gstin.strip().upper()
    err = validate_gstin(supplier_gstin)
    if err:
        raise HTTPException(status_code=422, detail=err)
    _check_state(data.place_of_supply)
    if _mock_enabled():
        return api_response(True, {"id": "mock-b2b-rc-supply", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    from services.audit_service import log_event
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = _resolve(db, firm_id, data.client_id, data.gstin)
    row = svc.record_b2b_rc_supply(
        db, firm_id, data.client_id, gstin=registration.gstin,
        financial_year=data.financial_year, supplier_gstin=supplier_gstin,
        place_of_supply=data.place_of_supply, rate_bps=data.rate_bps,
        taxable_value_paise=data.taxable_value_paise,
        igst_paise=data.igst_paise, cgst_paise=data.cgst_paise,
        sgst_paise=data.sgst_paise, cess_paise=data.cess_paise,
        notes=data.notes, actor_id=current_user.get("id"))
    log_event(firm_id or "", "gstr4_annual_b2b_rc_supply", row.get("id") or "",
              "record", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.delete("/b2b-rc-supplies/{supply_id}")
def delete_b2b_rc_supply(
    supply_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": supply_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    from services.audit_service import log_event
    row = svc.delete_b2b_rc_supply(get_supabase(), current_user.get("firm_id"), supply_id)
    log_event(current_user.get("firm_id") or "", "gstr4_annual_b2b_rc_supply",
              supply_id, "delete", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": supply_id, "deleted": True})


@router.get("/urp-supplies")
def list_urp_supplies(
    client_id: str = Query(...),
    financial_year: Annotated[FYLabel, Query(...)] = ...,
    gstin: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("gst", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, [])
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = _resolve(db, firm_id, client_id, gstin)
    return api_response(True, svc.list_urp_supplies(
        db, firm_id, client_id, registration.gstin, financial_year))


@router.post("/urp-supplies")
def record_urp_supply(
    data: UrpSupplyIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, data.client_id)
    counterparty_pan = (data.counterparty_pan or "").strip().upper() or None
    if counterparty_pan:
        err = validate_pan(counterparty_pan)
        if err:
            raise HTTPException(status_code=422, detail=err)
    _check_state(data.place_of_supply)
    if data.supply_type is not None and not data.reverse_charge:
        raise HTTPException(status_code=422, detail=(
            "Supply type is recorded only for a reverse-charge row — "
            "migration 422's own CHECK constraint refuses this at the "
            "database too, and the sheet has nothing for it to describe "
            "when the supplier already charged the tax."))
    if data.rate_bps is not None and not data.reverse_charge:
        raise HTTPException(status_code=422, detail=(
            "A rate is recorded only for a reverse-charge row — the "
            "supplier's own supply carries no self-assessed rate here."))
    if _mock_enabled():
        return api_response(True, {"id": "mock-urp-supply", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    from services.audit_service import log_event
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = _resolve(db, firm_id, data.client_id, data.gstin)
    row = svc.record_urp_supply(
        db, firm_id, data.client_id, gstin=registration.gstin,
        financial_year=data.financial_year, counterparty_pan=counterparty_pan,
        reverse_charge=data.reverse_charge, place_of_supply=data.place_of_supply,
        supply_type=data.supply_type, rate_bps=data.rate_bps,
        taxable_value_paise=data.taxable_value_paise,
        igst_paise=data.igst_paise, cgst_paise=data.cgst_paise,
        sgst_paise=data.sgst_paise, cess_paise=data.cess_paise,
        notes=data.notes, actor_id=current_user.get("id"))
    log_event(firm_id or "", "gstr4_annual_urp_supply", row.get("id") or "",
              "record", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.delete("/urp-supplies/{supply_id}")
def delete_urp_supply(
    supply_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": supply_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    from services.audit_service import log_event
    row = svc.delete_urp_supply(get_supabase(), current_user.get("firm_id"), supply_id)
    log_event(current_user.get("firm_id") or "", "gstr4_annual_urp_supply",
              supply_id, "delete", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": supply_id, "deleted": True})


@router.get("/import-of-services")
def list_import_of_services(
    client_id: str = Query(...),
    financial_year: Annotated[FYLabel, Query(...)] = ...,
    gstin: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("gst", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, [])
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = _resolve(db, firm_id, client_id, gstin)
    return api_response(True, svc.list_import_of_services(
        db, firm_id, client_id, registration.gstin, financial_year))


@router.post("/import-of-services")
def record_import_of_service(
    data: ImportOfServiceIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, data.client_id)
    _check_state(data.place_of_supply)
    if _mock_enabled():
        return api_response(True, {"id": "mock-imps", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    from services.audit_service import log_event
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = _resolve(db, firm_id, data.client_id, data.gstin)
    row = svc.record_import_of_service(
        db, firm_id, data.client_id, gstin=registration.gstin,
        financial_year=data.financial_year, place_of_supply=data.place_of_supply,
        rate_bps=data.rate_bps, taxable_value_paise=data.taxable_value_paise,
        igst_paise=data.igst_paise, cess_paise=data.cess_paise,
        notes=data.notes, actor_id=current_user.get("id"))
    log_event(firm_id or "", "gstr4_annual_import_of_service", row.get("id") or "",
              "record", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.delete("/import-of-services/{supply_id}")
def delete_import_of_service(
    supply_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": supply_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services import gstr4_annual_service as svc
    from services.audit_service import log_event
    row = svc.delete_import_of_service(get_supabase(), current_user.get("firm_id"), supply_id)
    log_event(current_user.get("firm_id") or "", "gstr4_annual_import_of_service",
              supply_id, "delete", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": supply_id, "deleted": True})
