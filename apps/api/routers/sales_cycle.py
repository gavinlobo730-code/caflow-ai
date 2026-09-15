"""The sales cycle before the tax invoice (SALES-21).

Quotation, proforma invoice, sales order and delivery challan. Thin surface
over `services/sales_cycle_service.py`, which is in turn a fetch layer over
`domain/sales/order_cycle.py` (the commercial chain) and
`domain/gst/delivery_challan.py` (CGST Rule 55). Nothing here decides anything
either module decides.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. None of these documents is filed,
# transmitted or posted; the tax invoice is still raised by hand from the
# Sales screen, which is the document that declares the supply.
"""
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from models.sales_cycle import (
    DeliveryChallanIn, DeliveryChallanUpdateIn, QuotationIn, QuotationUpdateIn,
    SalesOrderIn, SalesOrderUpdateIn,
)
from domain.gst import delivery_challan as dc
from domain.sales import order_cycle as oc
from services import sales_cycle_service as svc

router = APIRouter(prefix="/api/sales-cycle", tags=["sales_cycle"])


def _mock() -> bool:
    from core.config import settings as _s
    return bool(getattr(_s, "USE_MOCK_DATA", False))


def _db():
    from core.supabase_client import get_supabase
    return get_supabase()


@router.get("/vocabulary")
def vocabulary(current_user: dict = Depends(rbac("invoice", "read"))):
    """Every label and every statutory sentence the screens render.

    Served rather than spelled in TypeScript, for the reason the Schedule III
    captions are: a second copy of a vocabulary drifts, and here the drift
    would be a document headed "Invoice" that is not one.
    """
    return api_response(True, {
        "quote_kinds": [{"value": k, "label": oc.KIND_TITLES[k]}
                        for k in oc.QUOTE_KINDS],
        "quote_statuses": list(oc.QUOTE_STATUSES),
        "order_statuses": list(oc.ORDER_STATUSES),
        "challan_statuses": list(oc.CHALLAN_STATUSES),
        "challan_reasons": [{"value": r, "label": dc.REASON_LABELS[r],
                             "is_a_supply": r in dc.REASONS_THAT_ARE_A_SUPPLY}
                            for r in dc.REASONS],
        "goods_kinds": [
            {"value": dc.GOODS_KIND_INPUTS, "label": "Inputs (one year, s.143(1))"},
            {"value": dc.GOODS_KIND_CAPITAL_GOODS,
             "label": "Capital goods (three years, s.143(1))"},
            {"value": dc.GOODS_KIND_EXCLUDED,
             "label": "Moulds, dies, jigs, fixtures or tools (no period)"},
        ],
        "not_a_tax_invoice": oc.NOT_A_TAX_INVOICE,
        "no_tax_on_a_non_supply": dc.NO_TAX_ON_A_NON_SUPPLY,
        "job_work_exclusion": dc.JOB_WORK_EXCLUSION,
        "rule_55_5_steps": list(dc.RULE_55_5_STEPS),
        "copies": [{"copy": c, "legend": legend} for c, legend in dc.COPIES],
        "itc_04": dc.itc_04_period(),
    })


# ── Quotations and proforma invoices ────────────────────────────────────────

@router.get("/quotations")
def list_quotations(
    client_id: str = Query(...),
    kind: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("invoice", "read")),
):
    assert_client_access(current_user, client_id)
    if kind and kind not in oc.QUOTE_KINDS:
        raise HTTPException(status_code=422, detail=f"Unknown kind {kind!r}.")
    if _mock():
        return api_response(True, [])
    return api_response(True, svc.list_quotations(
        _db(), current_user.get("firm_id"), client_id, kind))


@router.get("/quotations/{quotation_id}/lines")
def quotation_lines(
    quotation_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, [])
    return api_response(True, svc.quotation_lines(
        _db(), current_user.get("firm_id"), quotation_id))


@router.post("/quotations")
def create_quotation(
    payload: QuotationIn,
    current_user: dict = Depends(rbac("invoice", "write")),
):
    assert_client_access(current_user, payload.client_id)
    if _mock():
        return api_response(True, {"id": "mock-quotation",
                                   "kind": payload.kind,
                                   "document_no": payload.document_no})
    return api_response(True, svc.create_quotation(
        _db(), current_user.get("firm_id"), payload.model_dump(),
        current_user.get("id")))


@router.patch("/quotations/{quotation_id}")
def update_quotation(
    quotation_id: str,
    payload: QuotationUpdateIn,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """Amend a quotation. A converted or cancelled one is refused — raise a
    new document, which costs nothing."""
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"id": quotation_id})
    return api_response(True, svc.update_quotation(
        _db(), current_user.get("firm_id"), quotation_id,
        payload.model_dump()))


# ── Sales orders ────────────────────────────────────────────────────────────

@router.get("/orders")
def list_orders(
    client_id: str = Query(...),
    only_open: bool = Query(False),
    current_user: dict = Depends(rbac("invoice", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, [])
    return api_response(True, svc.list_orders(
        _db(), current_user.get("firm_id"), client_id, only_open))


@router.get("/orders/{order_id}/position")
def order_position(
    order_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "read")),
):
    """What this order still has open, per line. Derived, never stored."""
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"order": None, "lines": [],
                                   "status_would_be": "confirmed",
                                   "gaps": [svc.INVOICED_QUANTITY_IS_NOT_LINKED]})
    return api_response(True, svc.order_open_position(
        _db(), current_user.get("firm_id"), order_id))


@router.post("/orders")
def create_order(
    payload: SalesOrderIn,
    current_user: dict = Depends(rbac("invoice", "write")),
):
    assert_client_access(current_user, payload.client_id)
    if _mock():
        return api_response(True, {"id": "mock-order",
                                   "document_no": payload.document_no})
    return api_response(True, svc.create_order(
        _db(), current_user.get("firm_id"), payload.model_dump(),
        current_user.get("id")))


@router.patch("/orders/{order_id}")
def update_order(
    order_id: str,
    payload: SalesOrderUpdateIn,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """Amend a sales order. An order with a delivery against it keeps its
    lines — a challan was already checked for over-delivery against them."""
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"id": order_id})
    return api_response(True, svc.update_order(
        _db(), current_user.get("firm_id"), order_id, payload.model_dump()))


# ── Delivery challans ───────────────────────────────────────────────────────

@router.get("/challans")
def list_challans(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "read")),
):
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, [])
    return api_response(True, svc.list_challans(
        _db(), current_user.get("firm_id"), client_id))


@router.get("/challans/{challan_id}")
def challan_particulars(
    challan_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "read")),
):
    """Rule 55's nine clauses against this challan, the three copies, and the
    s.143 or s.31(7) clock it is running. Writes nothing."""
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"challan": None, "lines": [],
                                   "particulars": [], "missing": [],
                                   "copies": [], "clock": {},
                                   "ca_review_required": True})
    db = _db()
    # Rule 55(1)(ii)'s consigner is the CLIENT whose goods are moving — not the
    # CA firm. SALES-01 was exactly this mistake on the tax invoice: the PDF
    # named the practice as the supplier, with the practice's own GSTIN, on the
    # client's outward document.
    res = (db.table("clients")
           .select("id, client_name, legal_name, trade_name, gstin, "
                   "address_line1, address_line2, city, state, pincode")
           .eq("firm_id", current_user.get("firm_id")).eq("id", client_id)
           .limit(1).execute())
    consigner = None
    if res.data:
        row = res.data[0]
        consigner = {
            "legal_name": row.get("legal_name") or row.get("trade_name")
            or row.get("client_name"),
            "gstin": row.get("gstin"),
            "address": ", ".join(
                str(b).strip() for b in (row.get("address_line1"),
                                         row.get("address_line2"),
                                         row.get("city"), row.get("state"),
                                         row.get("pincode")) if (b or "").strip()),
        }
    return api_response(True, svc.challan_particulars(
        db, current_user.get("firm_id"), challan_id, consigner=consigner))


@router.post("/challans")
def create_challan(
    payload: DeliveryChallanIn,
    current_user: dict = Depends(rbac("invoice", "write")),
):
    assert_client_access(current_user, payload.client_id)
    if _mock():
        return api_response(True, {"id": "mock-challan",
                                   "document_no": payload.document_no,
                                   "reason": payload.reason})
    return api_response(True, svc.create_challan(
        _db(), current_user.get("firm_id"), payload.model_dump(),
        current_user.get("id")))


@router.patch("/challans/{challan_id}")
def update_challan(
    challan_id: str,
    payload: DeliveryChallanUpdateIn,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """Amend a challan.

    `received_back_on` is the one field here that changes what is OWED: a
    challan carrying it is no longer running towards a deemed supply under
    s.143(3)/(4). Everything else on this door is a correction to what the
    document SAYS — the consignee, the transporter, the vehicle — which
    Rule 55(1) requires and which a CA fills in when the lorry is booked.
    """
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"id": challan_id,
                                   "received_back_on": payload.received_back_on,
                                   "status": payload.status or "draft"})
    return api_response(True, svc.update_challan(
        _db(), current_user.get("firm_id"), challan_id, payload.model_dump()))
