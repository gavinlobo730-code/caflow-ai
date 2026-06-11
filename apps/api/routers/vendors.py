"""Vendor master — CRUD with GSTIN validation.
Client-scoped: every vendor belongs to a CA client.
CGST Act Section 25: Registration of person. GSTIN format: 2-digit state + PAN (10) + entity + Z + check.
IT Act Section 194C/194I/194J: TDS applicable vendors tracked here.
"""
import os
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from models.parties import VendorIn, VendorUpdateIn
from core.permissions import rbac
from services.audit_service import log_event
from services.timeline_service import timeline_service


def _current_fy_long() -> str:
    """Return full financial year string like '2025-26'. Indian FY: April 1 – March 31."""
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.vendors")

# CGST Act §25: GSTIN format validation
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")

router = APIRouter(prefix="/api/vendors", tags=["vendors"])

# ---------------------------------------------------------------------------
# Mock store
# ---------------------------------------------------------------------------
MOCK_VENDORS: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_gstin(gstin: str, state_code: Optional[str] = None) -> None:
    """Raise 422 if GSTIN is syntactically invalid or state code mismatches."""
    if not GSTIN_RE.match(gstin):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid GSTIN format: '{gstin}'. Expected: 2-digit state + PAN(10) + entity + Z + check.",
        )
    if state_code and gstin[:2] != state_code:
        raise HTTPException(
            status_code=422,
            detail=f"GSTIN state code '{gstin[:2]}' does not match provided state_code '{state_code}'.",
        )


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_vendors(
    client_id: str = Query(..., description="CA client ID — required"),
    include_inactive: bool = Query(False),
    current_user: dict = Depends(rbac("client", "read")),
):
    """List vendors for a client."""
    try:
        if _USE_MOCK:
            firm_id = current_user.get("firm_id")
            result = [v for v in MOCK_VENDORS if v["client_id"] == client_id and v.get("firm_id") == firm_id]
            if not include_inactive:
                result = [v for v in result if v.get("is_active", True)]
            return api_response(True, result)

        from core.supabase_client import get_supabase
        db = get_supabase()
        q = db.table("vendors").select("*").eq("client_id", client_id)
        if not include_inactive:
            q = q.eq("is_active", True)
        resp = q.execute()
        return api_response(True, resp.data or [])
    except Exception as e:
        _logger.error("list_vendors: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.post("/")
def create_vendor(
    data: VendorIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Create a vendor. IT Act §194C/194I/194J: TDS section tracked per vendor."""
    try:
        payload = data.model_dump()
        payload["firm_id"] = current_user.get("firm_id")
        payload["is_active"] = True
        payload["created_at"] = datetime.now(timezone.utc).isoformat()
        data = payload

        if _USE_MOCK:
            data["id"] = str(uuid.uuid4())
            MOCK_VENDORS.append(data)
            return api_response(True, data)

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("vendors").insert(data).execute()
        vendor = resp.data[0] if resp.data else data
        vendor_id = vendor.get("id", "")
        log_event(
            data["firm_id"], "vendor", vendor_id,
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=vendor,
        )
        timeline_service.log_timeline_event(
            client_id=data.get("client_id", ""),
            firm_id=data.get("firm_id", ""),
            financial_year=_current_fy_long(),
            category="accounting",
            event_type="vendor_created",
            title=f"Vendor {data.get('name', '')} added",
            description="New vendor added to the system.",
            severity="info",
            entity_type="vendor",
            entity_id=vendor_id,
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )
        return api_response(True, vendor)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_vendor: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.get("/{vendor_id}")
def get_vendor(
    vendor_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """Get a single vendor by ID."""
    try:
        if _USE_MOCK:
            vendor = next((v for v in MOCK_VENDORS if v["id"] == vendor_id), None)
            if not vendor:
                raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
            return api_response(True, vendor)

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("vendors").select("*").eq("id", vendor_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
        return api_response(True, resp.data[0])
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_vendor: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.patch("/{vendor_id}")
def update_vendor(
    vendor_id: str,
    data: VendorUpdateIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Partial update of vendor."""
    try:
        payload = data.model_dump(exclude_none=True)
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        data = payload

        if _USE_MOCK:
            for i, v in enumerate(MOCK_VENDORS):
                if v["id"] == vendor_id:
                    MOCK_VENDORS[i] = {**v, **data}
                    return api_response(True, MOCK_VENDORS[i])
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("vendors").update(data).eq("id", vendor_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
        updated = resp.data[0]
        log_event(
            current_user.get("firm_id", ""), "vendor", vendor_id,
            "update", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=updated,
        )
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_vendor: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.delete("/{vendor_id}")
def delete_vendor(
    vendor_id: str,
    current_user: dict = Depends(rbac("client", "delete")),
):
    """Soft delete — Partner only (client.delete RBAC)."""
    try:
        if _USE_MOCK:
            for i, v in enumerate(MOCK_VENDORS):
                if v["id"] == vendor_id:
                    MOCK_VENDORS[i]["is_active"] = False
                    return api_response(True, {"id": vendor_id, "is_active": False})
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("vendors").update({"is_active": False}).eq("id", vendor_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
        log_event(
            current_user.get("firm_id", ""), "vendor", vendor_id,
            "delete", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
        )
        return api_response(True, {"id": vendor_id, "is_active": False})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_vendor: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.get("/{vendor_id}/outstanding")
def get_vendor_outstanding(
    vendor_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """
    Outstanding payable = sum of net_payable_paise on unpaid purchase bills
    MINUS total purchase_payments made against this vendor.
    All arithmetic in integer paise.
    """
    try:
        if _USE_MOCK:
            return api_response(True, {
                "vendor_id": vendor_id,
                "outstanding_paise": 0,
            })

        from core.supabase_client import get_supabase
        db = get_supabase()

        # Verify vendor exists
        v_resp = db.table("vendors").select("id").eq("id", vendor_id).limit(1).execute()
        if not v_resp.data:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")

        # Sum outstanding purchase bills (net_payable_paise = total - tds, i.e. what we owe)
        bills_resp = (
            db.table("purchase_bills")
            .select("id,net_payable_paise,status")
            .eq("vendor_id", vendor_id)
            .not_.in_("status", ["paid", "cancelled"])
            .execute()
        )
        total_bills_paise = sum(
            b.get("net_payable_paise", 0) for b in (bills_resp.data or [])
        )

        # Sum payments already made
        payments_resp = (
            db.table("purchase_payments")
            .select("amount_paise")
            .eq("vendor_id", vendor_id)
            .execute()
        )
        total_paid_paise = sum(
            p.get("amount_paise", 0) for p in (payments_resp.data or [])
        )

        outstanding_paise = total_bills_paise - total_paid_paise

        return api_response(True, {
            "vendor_id": vendor_id,
            "outstanding_paise": outstanding_paise,
        })
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_vendor_outstanding: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")
