"""What an e-commerce operator's sellers supplied through it (GST-25, GSTR-8).

WRITES ARE `gst.compute` (the tier every recording endpoint in
`routers/gst_workspace.py` — the ITC register reversal/reclaim, for instance —
already uses; there is no `gst.write` action), READS `gst.read`. Nothing here
transmits anything to any portal; `services.gst_return_service
.gstr8_statement` is the only reader that turns these rows into a statement.
"""
from __future__ import annotations

import os

from typing import Annotated, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from core.authz import assert_client_access
from core.permissions import rbac
from core.validators import validate_gstin
from domain.gst import gstr8
from domain.gst.validator import VALID_STATE_CODES
from models.common import api_response
from models.gst_period import PeriodMMYYYY

router = APIRouter(prefix="/api/ecommerce-operator", tags=["ecommerce_operator"])


def _mock_enabled() -> bool:
    return not os.environ.get("SUPABASE_URL")


class SupplyIn(BaseModel):
    """One registered seller's figures for a period — GSTR-8 Table 3.

    `gstin` is the OPERATOR's own registration this row is filed under
    (GST-20's multi-registration shape); omit it to mean the primary.
    """
    client_id: str
    gstin: Optional[str] = None
    period: PeriodMMYYYY
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
    period: PeriodMMYYYY
    enrolment_id: str
    gross_value_paise: int = 0
    returns_paise: int = 0
    notes: Optional[str] = None


def _state_code_or_none(v: Optional[str]) -> Optional[str]:
    """A place of supply as a GST state code, or None for a blank. The offline utility reads the first two characters of its
    "code - State" dropdown, so only the code is kept; a code that is not a place of supply is refused in words."""
    v = (v or "").strip()
    if not v:
        return None
    if v not in VALID_STATE_CODES:
        raise ValueError(f"'{v}' is not a GST state code, so it cannot be a place of supply.")
    return v


class AmendmentIn(BaseModel):
    """One row of GSTR-8 Table 4: the figures a registered seller's row of an EARLIER month is revised to.

    `period` is the statement this amendment is declared in and `original_period` the month whose row it amends (the utility's
    `ofp`); `original_supplier_gstin` / `original_place_of_supply` name that row (`ostin`, `opos`) and the rest are the revised figures
    in Table 3's own shape. `action` is the utility's own Add / Delete choice, kept as chosen. Amounts are non-negative, as the utility
    requires ("Invalid Amount").
    """
    client_id: str
    gstin: Optional[str] = None
    period: PeriodMMYYYY
    original_period: PeriodMMYYYY
    original_supplier_gstin: str
    original_place_of_supply: Optional[str] = None
    supplier_gstin: str
    place_of_supply: Optional[str] = None
    gross_registered_paise: int = Field(0, ge=0)
    returns_registered_paise: int = Field(0, ge=0)
    gross_unregistered_paise: int = Field(0, ge=0)
    returns_unregistered_paise: int = Field(0, ge=0)
    igst_paise: int = Field(0, ge=0)
    cgst_paise: int = Field(0, ge=0)
    sgst_paise: int = Field(0, ge=0)
    action: Literal["add", "delete"]
    notes: Optional[str] = None

    _pos = field_validator("original_place_of_supply", "place_of_supply")(_state_code_or_none)


class UnregisteredAmendmentIn(BaseModel):
    """One row of GSTR-8 Table 4.1: the figures an Enrolment-ID seller's row of an EARLIER month is revised to (`ofp`, `oeid`, `eid`,
    `grsval`, `supret`, `flag`). An Enrolment ID is kept as typed, as in Table 3.1."""
    client_id: str
    gstin: Optional[str] = None
    period: PeriodMMYYYY
    original_period: PeriodMMYYYY
    original_enrolment_id: str
    enrolment_id: str
    gross_value_paise: int = Field(0, ge=0)
    returns_paise: int = Field(0, ge=0)
    action: Literal["add", "delete"]
    notes: Optional[str] = None


def _refuse_an_original_month_that_is_not_earlier(original_period: str, period: str) -> None:
    """The utility's own refusal, in its words: an amendment corrects a row an EARLIER month declared."""
    problem = gstr8.original_period_problem(original_period, period)
    if problem:
        raise HTTPException(status_code=422, detail=problem)


@router.get("/supplies")
def list_supplies(
    client_id: str = Query(...),
    *,
    period: Annotated[PeriodMMYYYY, Query()],
    gstin: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("gst", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"registered": [], "unregistered": [], "amendments": [], "unregistered_amendments": []})
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
        # Table 4 / 4.1: the rows this month's statement declares against EARLIER months (POST-A-056).
        "amendments": eco_svc.list_amendments(db, firm_id, client_id, registration.gstin, period),
        "unregistered_amendments": eco_svc.list_unregistered_amendments(
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
    row = eco_svc.delete_supply(get_supabase(), current_user.get("firm_id"), client_id, supply_id)
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
                                             current_user.get("firm_id"), client_id, supply_id)
    log_event(current_user.get("firm_id") or "",
              "ecommerce_operator_unregistered_supply", supply_id, "delete",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": supply_id, "deleted": True})


@router.post("/amendments")
def record_amendment(
    data: AmendmentIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """GSTR-8 Table 4: record (or correct) one revision of a registered seller's row of an earlier month. Prepare-only."""
    assert_client_access(current_user, data.client_id)
    original_gstin = data.original_supplier_gstin.strip().upper()
    revised_gstin = data.supplier_gstin.strip().upper()
    # Both are the GSTIN the return names; a well-formed WRONG one is worse than an obviously wrong one (see `record_supply`).
    for gstin in (original_gstin, revised_gstin):
        err = validate_gstin(gstin)
        if err:
            raise HTTPException(status_code=422, detail=err)
    _refuse_an_original_month_that_is_not_earlier(data.original_period, data.period)
    if _mock_enabled():
        return api_response(True, {"id": "mock-amendment", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import client_gst_registration_service as regs
    from services import ecommerce_operator_service as eco_svc
    from services.audit_service import log_event
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = regs.resolve(db, firm_id, data.client_id, data.gstin)
    row = eco_svc.record_amendment(
        db, firm_id, data.client_id, gstin=registration.gstin, period=data.period,
        original_period=data.original_period, original_supplier_gstin=original_gstin,
        original_place_of_supply=data.original_place_of_supply,
        supplier_gstin=revised_gstin, place_of_supply=data.place_of_supply,
        gross_registered_paise=data.gross_registered_paise,
        returns_registered_paise=data.returns_registered_paise,
        gross_unregistered_paise=data.gross_unregistered_paise,
        returns_unregistered_paise=data.returns_unregistered_paise,
        igst_paise=data.igst_paise, cgst_paise=data.cgst_paise, sgst_paise=data.sgst_paise,
        action=data.action, notes=data.notes, actor_id=current_user.get("id"))
    log_event(firm_id or "", "ecommerce_operator_supply_amendment", row.get("id") or "",
              "record", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.delete("/amendments/{amendment_id}")
def delete_amendment(
    amendment_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": amendment_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services import ecommerce_operator_service as eco_svc
    from services.audit_service import log_event
    row = eco_svc.delete_amendment(get_supabase(), current_user.get("firm_id"), client_id, amendment_id)
    log_event(current_user.get("firm_id") or "", "ecommerce_operator_supply_amendment",
              amendment_id, "delete", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": amendment_id, "deleted": True})


@router.post("/unregistered-amendments")
def record_unregistered_amendment(
    data: UnregisteredAmendmentIn,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """GSTR-8 Table 4.1: record (or correct) one revision of an Enrolment-ID seller's row of an earlier month. Prepare-only."""
    assert_client_access(current_user, data.client_id)
    original_eid = data.original_enrolment_id.strip()
    revised_eid = data.enrolment_id.strip()
    if not original_eid or not revised_eid:
        raise HTTPException(status_code=422, detail="Both the original and the revised Enrolment ID are required.")
    _refuse_an_original_month_that_is_not_earlier(data.original_period, data.period)
    if _mock_enabled():
        return api_response(True, {"id": "mock-unreg-amendment", **data.model_dump()})
    from core.supabase_client import get_supabase
    from services import client_gst_registration_service as regs
    from services import ecommerce_operator_service as eco_svc
    from services.audit_service import log_event
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    registration = regs.resolve(db, firm_id, data.client_id, data.gstin)
    row = eco_svc.record_unregistered_amendment(
        db, firm_id, data.client_id, gstin=registration.gstin, period=data.period,
        original_period=data.original_period, original_enrolment_id=original_eid, enrolment_id=revised_eid,
        gross_value_paise=data.gross_value_paise, returns_paise=data.returns_paise,
        action=data.action, notes=data.notes, actor_id=current_user.get("id"))
    log_event(firm_id or "", "ecommerce_operator_unregistered_supply_amendment",
              row.get("id") or "", "record", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.delete("/unregistered-amendments/{amendment_id}")
def delete_unregistered_amendment(
    amendment_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "compute")),
):
    assert_client_access(current_user, client_id)
    if _mock_enabled():
        return api_response(True, {"id": amendment_id, "deleted": True})
    from core.supabase_client import get_supabase
    from services import ecommerce_operator_service as eco_svc
    from services.audit_service import log_event
    row = eco_svc.delete_unregistered_amendment(get_supabase(), current_user.get("firm_id"), client_id, amendment_id)
    log_event(current_user.get("firm_id") or "",
              "ecommerce_operator_unregistered_supply_amendment", amendment_id, "delete",
              actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), old_data=row)
    return api_response(True, {"id": amendment_id, "deleted": True})
