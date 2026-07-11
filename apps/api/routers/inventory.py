"""
Inventory — stock register and per-item movement ledger for kind='good'
Product/Service catalogue items (migration 188; costing engine in
domain/inventory_service.py). Read-only: all stock movements are written as
a side effect of issuing a sales invoice or receiving a purchase bill
(routers/sales_invoices.py, routers/purchase_bills.py) or seeding an opening
balance (routers/service_catalogue.py) — never directly through this router.
"""
import os
import logging
from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional
from models.common import api_response
from core.permissions import rbac

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
