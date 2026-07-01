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
        # Tenant isolation: service-role bypasses RLS — firm_id is the only guard
        # against a cross-tenant read via a guessed client_id (H15). The mock path
        # above already firm-scopes; the DB path must match it.
        q = (db.table("vendors").select("*")
             .eq("firm_id", current_user.get("firm_id")).eq("client_id", client_id))
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
                # created_by FKs to public.users.id (internal), not the Supabase auth id.
                post_opening_balances(payload["firm_id"], payload.get("client_id"),
                                      created_by=current_user.get("id"))
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
        # Classify into a user-safe message; never echo raw DB internals (M11).
        msg = str(e).lower()
        if "duplicate" in msg or "unique" in msg:
            return api_response(False, None, "A vendor with this GSTIN or PAN already exists for this client.")
        if "foreign key" in msg or "violates" in msg:
            return api_response(False, None, "Vendor creation failed due to a data constraint.")
        if "not-null" in msg or "null value" in msg:
            return api_response(False, None, "Vendor creation failed — a required field is missing.")
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
                                      created_by=current_user.get("id"))
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
        firm_id = current_user.get("firm_id")

        # Tenant isolation: service-role bypasses RLS, so EVERY read here must be
        # firm-scoped — otherwise a guessed vendor_id leaks another firm's payables (H15).
        v_resp = (db.table("vendors").select("id")
                  .eq("id", vendor_id).eq("firm_id", firm_id).limit(1).execute())
        if not v_resp.data:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")

        # M5: outstanding = Σ (net_payable − paid) over NON-CANCELLED bills. Computing
        # per-bill from the bill's own paid_paise avoids the double-subtraction the old
        # code hit (a fully-paid bill was excluded from the sum yet its payment was still
        # subtracted). Payments now reconcile to the bill sub-ledger (H11).
        bills_resp = (
            db.table("purchase_bills")
            .select("id,net_payable_paise,paid_paise,debited_paise,status")
            .eq("firm_id", firm_id)
            .eq("vendor_id", vendor_id)
            .neq("status", "cancelled")
            .execute()
        )
        # Net payable per bill = net_payable − paid − debited (debit notes relieve it).
        outstanding_paise = sum(
            int(b.get("net_payable_paise", 0) or 0) - int(b.get("paid_paise", 0) or 0)
            - int(b.get("debited_paise", 0) or 0)
            for b in (bills_resp.data or [])
        )

        return api_response(True, {
            "vendor_id": vendor_id,
            "outstanding_paise": outstanding_paise,
        })
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_vendor_outstanding: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.get("/ap-aging")
def ap_aging(
    client_id: str = Query(..., description="CA client ID — required"),
    as_of: Optional[str] = Query(None, description="Aging as-of date (YYYY-MM-DD)"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Accounts-payable aging for a client — per-bill outstanding bucketed by age.
    Derived entirely from posted bills, payments and debit notes (firm-scoped)."""
    try:
        from core.supabase_client import get_supabase
        from services.vendor_statement_service import vendor_statement_service
        db = get_supabase()
        data = vendor_statement_service.ap_aging(db, current_user.get("firm_id"), client_id, as_of)
        return api_response(True, data)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("ap_aging: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")


@router.get("/{vendor_id}/statement")
def vendor_statement(
    vendor_id: str,
    client_id: str = Query(..., description="CA client ID — required"),
    start_date: str = Query(..., description="YYYY-MM-DD"),
    end_date: str = Query(..., description="YYYY-MM-DD"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Vendor account statement: opening payable, period bills/payments/debit notes
    with a running balance, and closing payable. Derived from posted data only."""
    try:
        from core.supabase_client import get_supabase
        from services.vendor_statement_service import vendor_statement_service
        db = get_supabase()
        data = vendor_statement_service.generate(
            db, current_user.get("firm_id"), client_id, vendor_id, start_date, end_date)
        return api_response(True, data)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("vendor_statement: %s", e)
        return api_response(False, None, "Unable to complete vendor operation. Please try again.")
