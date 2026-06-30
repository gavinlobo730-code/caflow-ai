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
    vendor_in: VendorIn,
    current_user: dict = Depends(rbac("client", "write")),
):
    """Create a vendor. IT Act §194C/194I/194J: TDS section tracked per vendor."""
    try:
        payload = vendor_in.model_dump()
        payload["firm_id"] = current_user.get("firm_id")
        payload["is_active"] = True
        payload["created_at"] = datetime.now(timezone.utc).isoformat()

        if _USE_MOCK:
            payload["id"] = str(uuid.uuid4())
            MOCK_VENDORS.append(payload)
            return api_response(True, payload)

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("vendors").insert(payload).execute()
        if not resp.data:
            _logger.error("create_vendor: Supabase insert returned no data. payload=%s", payload)
            raise HTTPException(
                status_code=500,
                detail="Vendor could not be saved to the database. Please try again.",
            )
        vendor = resp.data[0]
        vendor_id = vendor.get("id", "")

        # Auto-sync opening balances to the GL — no manual "post" step. Only when an
        # opening balance was entered. Idempotent regenerate; roll back on failure.
        if int(payload.get("opening_balance_paise") or 0) != 0:
            try:
                from services.opening_balance_service import post_opening_balances
                post_opening_balances(payload["firm_id"], payload.get("client_id"),
                                      created_by=current_user.get("auth_user_id"))
            except Exception as sync_err:
                _logger.error("create_vendor opening-balance sync failed; rolling back: %s", sync_err)
                try:
                    db.table("vendors").delete().eq("id", vendor_id).eq("firm_id", payload["firm_id"]).execute()
                except Exception:
                    pass
                return api_response(False, None, "Unable to save vendor. Please try again.")

        log_event(
            payload["firm_id"], "vendor", vendor_id,
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=vendor,
        )
        timeline_service.log_timeline_event(
            client_id=payload.get("client_id", ""),
            firm_id=payload.get("firm_id", ""),
            financial_year=_current_fy_long(),
            category="accounting",
            event_type="vendor_created",
            title=f"Vendor {payload.get('name', '')} added",
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
        _logger.error("create_vendor: %s", e, exc_info=True)
        # Surface a meaningful error — never expose raw DB internals to the client
        msg = str(e)
        if "duplicate" in msg.lower() or "unique" in msg.lower():
            return api_response(False, None, "A vendor with this GSTIN or PAN already exists for this client.")
        if "foreign key" in msg.lower() or "violates" in msg.lower():
            return api_response(False, None, f"Vendor creation failed due to a data constraint: {msg}")
        if "not-null" in msg.lower() or "null value" in msg.lower():
            return api_response(False, None, f"Vendor creation failed — a required field is missing: {msg}")
        return api_response(False, None, f"Vendor creation failed: {msg}")


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
        resp = db.table("vendors").select("*").eq("id", vendor_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
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
        firm_id = current_user.get("firm_id")
        prior_resp = db.table("vendors").select("*").eq("id", vendor_id).eq("firm_id", firm_id).limit(1).execute()
        if not prior_resp.data:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
        prior = prior_resp.data[0]

        # Tenant isolation (OOS-5): scope the write by firm_id. Under service-role
        # (RLS bypassed) an unscoped by-id update could mutate another firm's row.
        resp = db.table("vendors").update(data).eq("id", vendor_id).eq("firm_id", firm_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
        updated = resp.data[0]

        # Auto-sync opening balances only when the opening balance actually changed.
        if int(updated.get("opening_balance_paise") or 0) != int(prior.get("opening_balance_paise") or 0):
            try:
                from services.opening_balance_service import post_opening_balances
                post_opening_balances(firm_id, updated.get("client_id") or prior.get("client_id"),
                                      created_by=current_user.get("auth_user_id"))
            except Exception as sync_err:
                _logger.error("update_vendor opening-balance sync failed; rolling back: %s", sync_err)
                try:
                    db.table("vendors").update({k: prior.get(k) for k in data.keys()}).eq("id", vendor_id).eq("firm_id", firm_id).execute()
                except Exception:
                    pass
                return api_response(False, None, "Unable to save vendor. Please try again.")

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
        # Tenant isolation (OOS-5): firm-scope the soft-delete write.
        resp = db.table("vendors").update({"is_active": False}).eq("id", vendor_id).eq("firm_id", current_user.get("firm_id")).execute()
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
