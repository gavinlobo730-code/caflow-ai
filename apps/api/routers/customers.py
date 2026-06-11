"""Customer master — CRUD with GSTIN validation.
Client-scoped: every customer belongs to a CA client.
CGST Act Section 25: Registration of person. GSTIN format: 2-digit state + PAN (10) + entity + Z + check.
"""
import os
import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from core.permissions import rbac
from core.exceptions import NotFoundError
from services.audit_service import log_event
from services.timeline_service import timeline_service


def _current_fy_long() -> str:
    """Return full financial year string like '2025-26'. Indian FY: April 1 – March 31."""
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.customers")

# CGST Act §25: GSTIN format — 2-digit state code + 10-char PAN + entity digit + Z + check digit
GSTIN_RE = re.compile(r"^[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z]{1}[1-9A-Z]{1}Z[0-9A-Z]{1}$")

router = APIRouter(prefix="/api/customers", tags=["customers"])

# ---------------------------------------------------------------------------
# Mock store (used when SUPABASE_URL is not configured)
# ---------------------------------------------------------------------------
MOCK_CUSTOMERS: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _validate_gstin(gstin: str, state_code: Optional[str] = None) -> None:
    """Raise 422 if GSTIN is syntactically invalid or state code mismatch."""
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


def _get_next_seq_mock() -> int:
    return len(MOCK_CUSTOMERS) + 1


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_customers(
    client_id: str = Query(..., description="CA client ID — required"),
    include_inactive: bool = Query(False),
    current_user: dict = Depends(rbac("client", "read")),
):
    try:
        if _USE_MOCK:
            result = [c for c in MOCK_CUSTOMERS if c["client_id"] == client_id]
            if not include_inactive:
                result = [c for c in result if c.get("is_active", True)]
            return api_response(True, result)

        from core.supabase_client import get_supabase
        db = get_supabase()
        q = db.table("customers").select("*").eq("client_id", client_id)
        if not include_inactive:
            q = q.eq("is_active", True)
        resp = q.execute()
        return api_response(True, resp.data or [])
    except Exception as e:
        _logger.error("list_customers: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.post("/")
def create_customer(
    data: dict,
    current_user: dict = Depends(rbac("client", "write")),
):
    try:
        # Validate required fields
        if not data.get("name"):
            raise HTTPException(status_code=422, detail="name is required")
        if not data.get("client_id"):
            raise HTTPException(status_code=422, detail="client_id is required")

        # GSTIN validation if provided — CGST Act §25
        if data.get("gstin"):
            _validate_gstin(data["gstin"], data.get("state_code"))

        data["firm_id"] = current_user.get("firm_id")
        data["is_active"] = True
        data["created_at"] = datetime.now(timezone.utc).isoformat()

        if _USE_MOCK:
            data["id"] = str(uuid.uuid4())
            MOCK_CUSTOMERS.append(data)
            return api_response(True, data)

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("customers").insert(data).execute()
        customer = resp.data[0] if resp.data else data
        customer_id = customer.get("id", "")
        log_event(
            data["firm_id"], "customer", customer_id,
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=customer,
        )
        timeline_service.log_timeline_event(
            client_id=data.get("client_id", ""),
            firm_id=data.get("firm_id", ""),
            financial_year=_current_fy_long(),
            category="accounting",
            event_type="customer_created",
            title=f"Customer {data.get('name', '')} added",
            description="New customer added to the system.",
            severity="info",
            entity_type="customer",
            entity_id=customer_id,
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )
        return api_response(True, customer)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_customer: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.get("/outstanding")
def get_outstanding_summary(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("client", "read")),
):
    """Aggregate outstanding balances across all customers for a client."""
    try:
        if _USE_MOCK:
            return api_response(True, {"client_id": client_id, "total_outstanding_paise": 0, "customers": []})

        from core.supabase_client import get_supabase
        db = get_supabase()
        customers = db.table("customers").select("id,name,opening_balance_paise").eq("client_id", client_id).eq("is_active", True).execute()

        result = []
        for cust in (customers.data or []):
            inv_resp = (
                db.table("sales_invoices")
                .select("id,total_paise,paid_paise,status")
                .eq("customer_id", cust["id"])
                .not_.in_("status", ["paid", "cancelled"])
                .execute()
            )
            inv_outstanding = sum(
                (i.get("total_paise", 0) - i.get("paid_paise", 0))
                for i in (inv_resp.data or [])
            )
            # Integer arithmetic only; opening balance always >= 0
            opening = cust.get("opening_balance_paise") or 0
            result.append({
                "customer_id": cust["id"],
                "customer_name": cust["name"],
                "outstanding_paise": inv_outstanding + opening,
            })

        total = sum(r["outstanding_paise"] for r in result)
        return api_response(True, {"client_id": client_id, "total_outstanding_paise": total, "customers": result})
    except Exception as e:
        _logger.error("get_outstanding_summary: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.get("/{customer_id}")
def get_customer(
    customer_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    try:
        if _USE_MOCK:
            cust = next((c for c in MOCK_CUSTOMERS if c["id"] == customer_id), None)
            if not cust:
                raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
            return api_response(True, cust)

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("customers").select("*").eq("id", customer_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
        return api_response(True, resp.data[0])
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_customer: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.patch("/{customer_id}")
def update_customer(
    customer_id: str,
    data: dict,
    current_user: dict = Depends(rbac("client", "write")),
):
    try:
        if data.get("gstin"):
            _validate_gstin(data["gstin"], data.get("state_code"))

        data["updated_at"] = datetime.now(timezone.utc).isoformat()

        if _USE_MOCK:
            for i, c in enumerate(MOCK_CUSTOMERS):
                if c["id"] == customer_id:
                    MOCK_CUSTOMERS[i] = {**c, **data}
                    return api_response(True, MOCK_CUSTOMERS[i])
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("customers").update(data).eq("id", customer_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
        updated = resp.data[0]
        log_event(
            current_user.get("firm_id", ""), "customer", customer_id,
            "update", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=updated,
        )
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_customer: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.delete("/{customer_id}")
def delete_customer(
    customer_id: str,
    current_user: dict = Depends(rbac("client", "delete")),
):
    """Soft delete — Partner only (via client.delete RBAC)."""
    try:
        if _USE_MOCK:
            for i, c in enumerate(MOCK_CUSTOMERS):
                if c["id"] == customer_id:
                    MOCK_CUSTOMERS[i]["is_active"] = False
                    return api_response(True, {"id": customer_id, "is_active": False})
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("customers").update({"is_active": False}).eq("id", customer_id).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
        log_event(
            current_user.get("firm_id", ""), "customer", customer_id,
            "delete", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
        )
        return api_response(True, {"id": customer_id, "is_active": False})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_customer: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")


@router.get("/{customer_id}/outstanding")
def get_customer_outstanding(
    customer_id: str,
    current_user: dict = Depends(rbac("client", "read")),
):
    """
    Outstanding balance = sum of (total_paise - paid_paise) on open invoices
    PLUS opening_balance_paise.
    All arithmetic in integer paise.
    """
    try:
        if _USE_MOCK:
            return api_response(True, {
                "customer_id": customer_id,
                "outstanding_paise": 0,
                "invoices": [],
            })

        from core.supabase_client import get_supabase
        db = get_supabase()

        # Fetch customer for opening balance
        cust_resp = db.table("customers").select("opening_balance_paise").eq("id", customer_id).limit(1).execute()
        if not cust_resp.data:
            raise HTTPException(status_code=404, detail=f"Customer {customer_id} not found")
        opening_balance = cust_resp.data[0].get("opening_balance_paise") or 0

        inv_resp = (
            db.table("sales_invoices")
            .select("id,invoice_no,invoice_date,total_paise,paid_paise,status")
            .eq("customer_id", customer_id)
            .not_.in_("status", ["paid", "cancelled"])
            .execute()
        )
        invoices = inv_resp.data or []
        inv_outstanding = sum(
            (i.get("total_paise", 0) - i.get("paid_paise", 0))
            for i in invoices
        )
        total_outstanding = inv_outstanding + opening_balance  # integer paise

        return api_response(True, {
            "customer_id": customer_id,
            "outstanding_paise": total_outstanding,
            "invoices": invoices,
        })
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_customer_outstanding: %s", e)
        return api_response(False, None, "Unable to complete customer operation. Please try again.")
