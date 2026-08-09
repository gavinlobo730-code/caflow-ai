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
from core.authz import assert_client_access
from services.audit_service import log_event
from services.period_validation_service import period_validation_service

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.inventory")

router = APIRouter(prefix="/api/inventory", tags=["inventory"])


def _last_ledger_rows(db, firm_id: str, client_id: str, item_ids: set[str]) -> dict[str, dict]:
    """Each item's current (most-recently-inserted) ledger row — the same
    running_qty_units/running_avg_cost_paise/running_value_paise every new
    movement chains from (domain/inventory_service.py::_last_ledger_row) —
    fetched in bulk for the whole stock register instead of one row per
    item. Pages newest-first (created_at desc, matching _last_ledger_row's
    own ordering exactly) and stops as soon as every item has been seen,
    rather than scanning the client's entire movement history."""
    found: dict[str, dict] = {}
    remaining = set(item_ids)
    page_size = 1000
    offset = 0
    while remaining:
        resp = (
            db.table("inventory_stock_ledger")
            .select("service_catalogue_id, running_qty_units, running_avg_cost_paise, running_value_paise")
            .eq("firm_id", firm_id).eq("client_id", client_id)
            .order("created_at", desc=True)
            .range(offset, offset + page_size - 1)
            .execute()
        )
        page = resp.data or []
        if not page:
            break
        for row in page:
            sid = row["service_catalogue_id"]
            if sid in remaining:
                found[sid] = row
                remaining.discard(sid)
        if len(page) < page_size:
            break
        offset += page_size
    return found


@router.get("/items")
def list_stock_items(
    client_id: str = Query(..., description="CA client ID — stock is client-owned, same as the catalogue"),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Stock register: every kind='good' catalogue item for this client, with
    its current on-hand quantity, moving-average cost, and stock value —
    read from inventory_stock_ledger's running totals (the authoritative
    figures every posting chains from), not recomputed from
    service_catalogue's cache. qty * avg_cost re-rounds an already-rounded
    average cost at display time, which can drift a few paise per item from
    the ledger's exact cumulative value and, summed across the whole
    register, no longer ties to the Balance Sheet Inventory account. Items
    with no ledger history yet (never received a stock-in movement) show 0,
    same as before."""
    assert_client_access(current_user, client_id)
    try:
        if _USE_MOCK:
            return api_response(True, [])

        firm_id = current_user.get("firm_id")
        from core.supabase_client import get_supabase
        db = get_supabase()
        rows = (
            db.table("service_catalogue")
            .select("id, name, description, hsn_sac, unit, kind, is_active")
            .eq("firm_id", firm_id).eq("client_id", client_id).eq("kind", "good")
            .order("name").order("id")
            .execute().data
        ) or []
        last_rows = _last_ledger_rows(db, firm_id, client_id, {r["id"] for r in rows})
        for r in rows:
            last = last_rows.get(r["id"])
            qty = float(last["running_qty_units"]) if last else 0.0
            avg = int(last["running_avg_cost_paise"]) if last else 0
            value = int(last["running_value_paise"]) if last else 0
            r["stock_qty_units"] = qty
            r["avg_cost_paise"] = avg
            r["stock_value_paise"] = value
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
    assert_client_access(current_user, client_id)
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
    assert_client_access(current_user, data.client_id)
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
            # journal_entries.created_by FK references users(id), not auth_user_id.
            created_by=current_user.get("id"),
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
    assert_client_access(current_user, data.client_id)
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
            # journal_entries.created_by FK references users(id), not auth_user_id.
            reference_no=reference_no, created_by=current_user.get("id"),
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
