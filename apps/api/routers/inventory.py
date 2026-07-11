"""
Inventory — stock register, per-item movement ledger, and manual stock
adjustment for kind='good' Product/Service catalogue items (migration 188;
costing engine in domain/inventory_service.py). Most stock movements are
written as a side effect of issuing a sales invoice, receiving a purchase
bill, issuing a credit/debit note (routers/sales_invoices.py,
routers/purchase_bills.py, routers/credit_notes.py, routers/debit_notes.py),
or seeding an opening balance (routers/service_catalogue.py) — never
directly through this router. The one exception is POST .../adjust below:
a CA-initiated physical-count correction, damage, theft, destruction or
free-sample giveaway, the only movement with no other document to attach to.
"""
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from models.common import api_response
from models.inventory import StockAdjustmentIn, NrvWritedownIn
from core.permissions import rbac
from services.audit_service import log_event
from services.period_validation_service import period_validation_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.inventory")

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


@router.get("/items")
def list_stock_items(
    client_id: str = Query(..., description="CA client ID — stock is client-owned, same as the catalogue"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Stock register: every kind='good' catalogue item for this client, with
    its current on-hand quantity, moving-average cost, and stock value
    (qty * avg cost — a display figure, never persisted; the authoritative
    value lives in inventory_stock_ledger.running_value_paise)."""
    try:
        if _USE_MOCK:
            return api_response(True, [])

        firm_id = current_user.get("firm_id")
        from core.supabase_client import get_supabase
        db = get_supabase()
        rows = (
            db.table("service_catalogue")
            .select("id, name, description, hsn_sac, unit, kind, is_active, stock_qty_units, avg_cost_paise")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("kind", "good")
            .order("name")
            .execute().data
        ) or []
        for r in rows:
            qty = float(r.get("stock_qty_units") or 0)
            avg = int(r.get("avg_cost_paise") or 0)
            r["stock_value_paise"] = round(qty * avg)
        return api_response(True, rows)
    except Exception as e:
        _logger.error("list_stock_items: %s", e)
        return api_response(False, None, "Unable to load the stock register. Please try again.")


@router.get("/items/{service_catalogue_id}/ledger")
def get_item_stock_ledger(
    service_catalogue_id: str,
    client_id: str = Query(...),
    start_date: Optional[str] = Query(None),
    end_date: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Movement history for one stock item — mirrors the accounting Ledger
    view's shape (opening/running balance per row)."""
    try:
        if _USE_MOCK:
            return api_response(True, {"item": None, "lines": []})

        firm_id = current_user.get("firm_id")
        from core.supabase_client import get_supabase
        from domain.inventory_service import get_stock_ledger
        db = get_supabase()

        item_resp = (
            db.table("service_catalogue").select("id, name, unit, stock_qty_units, avg_cost_paise")
            .eq("id", service_catalogue_id).eq("firm_id", firm_id).eq("client_id", client_id)
            .limit(1).execute()
        )
        if not item_resp.data:
            raise HTTPException(status_code=404, detail="Stock item not found.")

        lines = get_stock_ledger(db, service_catalogue_id, start_date, end_date)
        return api_response(True, {"item": item_resp.data[0], "lines": lines})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_item_stock_ledger: %s", e)
        return api_response(False, None, "Unable to load the stock ledger. Please try again.")


@router.post("/items/{service_catalogue_id}/adjust")
def adjust_stock(
    service_catalogue_id: str,
    data: StockAdjustmentIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Manual stock adjustment — physical count correction, damage, theft,
    destruction, or free samples given away. The CA explicitly confirms both
    the quantity/direction and whether it triggers an ITC reversal (CGST Act
    §17(5)(h)) before this posts; never inferred or auto-triggered."""
    try:
        if data.direction == "increase" and data.reverse_itc:
            raise HTTPException(
                status_code=422,
                detail="ITC reversal only applies to a decrease (loss/write-off), not a surplus.",
            )
        if _USE_MOCK:
            return api_response(True, None)

        firm_id = current_user.get("firm_id")
        from core.supabase_client import get_supabase
        from domain.inventory_service import apply_stock_adjustment
        db = get_supabase()

        item_resp = (
            db.table("service_catalogue").select("id, kind")
            .eq("id", service_catalogue_id).eq("firm_id", firm_id).eq("client_id", data.client_id)
            .limit(1).execute()
        )
        if not item_resp.data:
            raise HTTPException(status_code=404, detail="Stock item not found.")
        if item_resp.data[0].get("kind") != "good":
            raise HTTPException(status_code=422, detail="Only stock-tracked products can be adjusted.")

        period_validation_service.validate_posting_date(firm_id or "", data.adjustment_date)

        reference_no = data.reference_no or f"ADJ-{data.adjustment_date}"
        movement = apply_stock_adjustment(
            db, firm_id=firm_id or "", client_id=data.client_id, service_catalogue_id=service_catalogue_id,
            movement_date=data.adjustment_date, quantity=data.quantity, direction=data.direction,
            reverse_itc=data.reverse_itc, reference_no=reference_no,
            created_by=current_user.get("auth_user_id"),
        )
        log_event(
            firm_id or "", "inventory_adjustment", service_catalogue_id, "create",
            actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
            new_data={
                "direction": data.direction, "quantity": data.quantity, "reason": data.reason,
                "reverse_itc": data.reverse_itc, "notes": data.notes,
            },
        )
        return api_response(True, movement)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("adjust_stock: %s", e)
        return api_response(False, None, "Unable to record the stock adjustment. Please try again.")


@router.post("/items/{service_catalogue_id}/writedown")
def writedown_stock_to_nrv(
    service_catalogue_id: str,
    data: NrvWritedownIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Write inventory down to net realisable value when NRV has fallen
    below the current moving-average cost (AS-2 / Ind AS 2 / ICDS-II:
    inventory must be carried at the LOWER of cost or NRV). No quantity
    change — value only. A no-op (200, data=null) if NRV is already >= the
    current average cost, or the item has no stock yet."""
    try:
        if _USE_MOCK:
            return api_response(True, None)

        firm_id = current_user.get("firm_id")
        from core.supabase_client import get_supabase
        from domain.inventory_service import apply_nrv_writedown
        db = get_supabase()

        item_resp = (
            db.table("service_catalogue").select("id, kind")
            .eq("id", service_catalogue_id).eq("firm_id", firm_id).eq("client_id", data.client_id)
            .limit(1).execute()
        )
        if not item_resp.data:
            raise HTTPException(status_code=404, detail="Stock item not found.")
        if item_resp.data[0].get("kind") != "good":
            raise HTTPException(status_code=422, detail="Only stock-tracked products can be written down.")

        period_validation_service.validate_posting_date(firm_id or "", data.writedown_date)

        reference_no = data.reference_no or f"NRV-{data.writedown_date}"
        movement = apply_nrv_writedown(
            db, firm_id=firm_id or "", client_id=data.client_id, service_catalogue_id=service_catalogue_id,
            movement_date=data.writedown_date, nrv_per_unit_paise=data.nrv_per_unit_paise,
            reference_no=reference_no, created_by=current_user.get("auth_user_id"),
        )
        log_event(
            firm_id or "", "inventory_nrv_writedown", service_catalogue_id, "create",
            actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
            new_data={"nrv_per_unit_paise": data.nrv_per_unit_paise, "notes": data.notes, "applied": bool(movement)},
        )
        return api_response(True, movement)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("writedown_stock_to_nrv: %s", e)
        return api_response(False, None, "Unable to record the write-down. Please try again.")
