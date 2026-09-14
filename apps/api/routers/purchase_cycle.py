"""The purchase cycle before the bill (PUR-25).

Purchase order, goods receipt, and the three-way match. Thin surface over
`services/purchase_cycle_service.py`, which is in turn a fetch layer over
`domain/purchases/order_cycle.py` (the commercial chain) and
`domain/purchases/three_way_match.py` (the comparison and the two statutes it
settles: CGST s.16(2)(b) and MSMED s.15 with s.2(b)).

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. Nothing here posts a journal, moves
# stock, or blocks a bill. The supplier's invoice is still received through the
# existing purchase path, which is what creates the expense, the input credit
# and the payable.
"""
from typing import Optional

from fastapi import APIRouter, Depends, Query

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from models.purchase_cycle import (
    GoodsReceiptIn, GoodsReceiptUpdateIn, PurchaseOrderIn,
    PurchaseOrderUpdateIn,
)
from domain.purchases import order_cycle as oc
from domain.purchases import three_way_match as twm
from services import purchase_cycle_service as svc

router = APIRouter(prefix="/api/purchase-cycle", tags=["purchase_cycle"])


def _mock() -> bool:
    from core.config import settings as _s
    return bool(getattr(_s, "USE_MOCK_DATA", False))


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


@router.get("/vocabulary")
def vocabulary(current_user: dict = Depends(rbac("accounting", "read"))):
    """Every label and every statutory sentence the screen renders.

    Served rather than spelled in TypeScript: a second copy of a statutory
    sentence drifts, and here the drift would be a CA told the wrong thing
    about when a credit is available or when a payment falls due.
    """
    return api_response(True, {
        "order_statuses": list(oc.ORDER_STATUSES),
        "order_open_statuses": list(oc.ORDER_OPEN_STATUSES),
        "receipt_statuses": list(oc.GRN_STATUSES),
        "posts_nothing": oc.POSTS_NOTHING,
        "section_16_2_b": twm.SECTION_16_2_B,
        "bill_to_ship_to": twm.BILL_TO_SHIP_TO_NOT_MODELLED,
        "msmed_acceptance": twm.MSMED_ACCEPTANCE,
        "no_tolerance": twm.NO_TOLERANCE_IS_APPLIED,
    })


# ── Purchase orders ─────────────────────────────────────────────────────────

@router.get("/orders")
def list_orders(
    client_id: str = Query(...),
    only_open: bool = Query(False),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, [])
    return api_response(True, svc.list_orders(
        _db(), current_user.get("firm_id"), client_id, only_open))


@router.get("/orders/{order_id}/lines")
def order_lines(
    order_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, [])
    return api_response(True, svc.order_lines(
        _db(), current_user.get("firm_id"), order_id))


@router.get("/orders/{order_id}/position")
def order_position(
    order_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """What this order still has open, per line. Derived, never stored."""
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"order": None, "lines": [],
                                   "status_would_be": "approved",
                                   "posts_nothing": oc.POSTS_NOTHING})
    return api_response(True, svc.order_open_position(
        _db(), current_user.get("firm_id"), order_id))


@router.post("/orders")
def create_order(
    payload: PurchaseOrderIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, payload.client_id)
    if _mock():
        return api_response(True, {"id": "mock-purchase-order",
                                   "document_no": payload.document_no})
    return api_response(True, svc.create_order(
        _db(), current_user.get("firm_id"), payload.model_dump(),
        current_user.get("id")))


@router.patch("/orders/{order_id}")
def update_order(
    order_id: str,
    payload: PurchaseOrderUpdateIn,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Amend a purchase order. One with a goods receipt against it keeps its
    lines — a receipt was already checked for over-receipt against them."""
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"id": order_id})
    return api_response(True, svc.update_order(
        _db(), current_user.get("firm_id"), order_id, payload.model_dump()))


# ── Goods receipts ──────────────────────────────────────────────────────────

@router.get("/receipts")
def list_receipts(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, [])
    return api_response(True, svc.list_receipts(
        _db(), current_user.get("firm_id"), client_id))


@router.get("/receipts/{receipt_id}/lines")
def receipt_lines(
    receipt_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, [])
    return api_response(True, svc.receipt_lines(
        _db(), current_user.get("firm_id"), receipt_id))


@router.post("/receipts")
def create_receipt(
    payload: GoodsReceiptIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    assert_client_access(current_user, payload.client_id)
    if _mock():
        return api_response(True, {"id": "mock-goods-receipt",
                                   "document_no": payload.document_no,
                                   "received_on": payload.received_on})
    return api_response(True, svc.create_receipt(
        _db(), current_user.get("firm_id"), payload.model_dump(),
        current_user.get("id")))


@router.patch("/receipts/{receipt_id}")
def update_receipt(
    receipt_id: str,
    payload: GoodsReceiptUpdateIn,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Amend a goods receipt, including recording an objection and its removal.

    That is the one edit here that moves a statutory date: MSMED s.2(b)'s
    Explanation runs the fifteen days from the day the objection was removed
    rather than the day of delivery.
    """
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"id": receipt_id})
    return api_response(True, svc.update_receipt(
        _db(), current_user.get("firm_id"), receipt_id, payload.model_dump()))


# ── The match ───────────────────────────────────────────────────────────────

@router.get("/bills/{bill_id}/match")
def match_bill(
    bill_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """This bill against its purchase order and its goods receipts.

    Reports. Blocks nothing, posts nothing, and applies no tolerance.
    """
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"bill_id": bill_id, "matched": False,
                                   "has_order": False, "has_receipt": False,
                                   "lines": [], "differences": [], "gaps": [],
                                   "caveats": [], "acceptance_date": None,
                                   "acceptance_source": "",
                                   "ca_review_required": True})
    return api_response(True, svc.match_bill(
        _db(), current_user.get("firm_id"), bill_id))
