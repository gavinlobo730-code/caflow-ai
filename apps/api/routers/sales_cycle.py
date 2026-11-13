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
import os
from typing import Annotated, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from core.authz import assert_client_access
from core.permissions import rbac
from models.common import api_response
from models.fy import FYLabel
from models.sales_cycle import (
    ChallanReturnIn, DeliveryChallanIn, DeliveryChallanUpdateIn, QuotationIn, QuotationUpdateIn,
    SalesOrderIn, SalesOrderUpdateIn,
)
from domain.gst import delivery_challan as dc
from domain.sales import order_cycle as oc
from services import sales_cycle_service as svc
from core import db_provider

router = APIRouter(prefix="/api/sales-cycle", tags=["sales_cycle"])


def _mock() -> bool:
    return not os.environ.get("SUPABASE_URL")


# Every route here is already rbac()-gated. get_supabase() is the
# RLS-enforced `authenticated` client under USE_USER_JWT, which has no
# INSERT/UPDATE/DELETE grant on sales_quotations/sales_orders/
# delivery_challans (or their line tables), so the whole sales cycle
# 500'd on both read and write. Same fix as routers/fixed_assets.py
# (PR #626).
_db = db_provider.service_db


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
    svc.row_of_client(_db(), "sales_quotations", current_user.get("firm_id"), quotation_id, client_id, "quotation")
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
    svc.row_of_client(_db(), "sales_quotations", current_user.get("firm_id"), quotation_id, client_id, "quotation")
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
    svc.row_of_client(_db(), "sales_orders", current_user.get("firm_id"), order_id, client_id, "sales order")
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
    svc.row_of_client(_db(), "sales_orders", current_user.get("firm_id"), order_id, client_id, "sales order")
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
    svc.row_of_client(db, "delivery_challans", current_user.get("firm_id"), challan_id, client_id, "delivery challan")
    # Rule 55(1)(ii)'s consigner is the CLIENT whose goods are moving — not the CA firm (`svc.consigner_of`, which the issue door reads too).
    consigner = svc.consigner_of(db, current_user.get("firm_id"), client_id)
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


@router.get("/itc-04")
def itc_04_statement(
    client_id: str = Query(...),
    *,
    financial_year: Annotated[FYLabel, Query(
        description="The financial year to derive the statement for, e.g. 2025-26")],
    window: Optional[str] = Query(
        None, description="One window key from `readings` — omit to list them all"),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """FORM GST ITC-04 (Rule 45(3)), derived from the job-work challans entered
    (GST-30). Writes nothing and files nothing.

    BOTH READINGS OF THE PERIOD, NEITHER CHOSEN. Rule 45(3)'s cadence turns on the
    principal's own preceding-year turnover and on a limit this environment could
    not confirm, so the windows of every reading are listed with how many rows
    each would carry, and the CA opens the one that applies. A turnover recorded
    for the preceding year is shown beside them as context and decides nothing.

    WHAT IS STILL OUT, and the s.143 date for it, is always returned: it is a
    fact about today and not about a window. A part return reduces the amount
    left to be deemed supplied and does not move the day the goods left.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. ITC-04 is furnished on the GST
    # portal by the principal.
    """
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"client_id": client_id, "readings": [],
                                   "outstanding": [], "gaps": [],
                                   "ca_review_required": True})
    from services import itc_04_service
    try:
        return api_response(True, itc_04_service.statement(
            _db(), current_user.get("firm_id"), client_id, financial_year,
            window=window))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/challans/{challan_id}/returns")
def record_challan_return(
    challan_id: str,
    payload: ChallanReturnIn,
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """Record goods coming back from a job worker, in whole or in part (GST-30).

    Recorded against the challan LINE the goods were sent on. Over-return is
    refused, never clamped, and lost or wasted quantity is recorded but is NEVER
    subtracted from what is outstanding. When the returns have brought every line
    back to nil the challan is marked received back through the one existing
    write, which stops the s.143 clock.

    The CLIENT in the body is asserted for access AND is what the line is looked
    up under, so another client's challan line cannot be reached by naming an
    assigned client beside somebody else's ids; `challan_id` in the path is
    checked against the line's own challan.
    """
    assert_client_access(current_user, payload.client_id)
    if _mock():
        return api_response(True, {"id": "mock-return", "challan_id": challan_id})
    from services import itc_04_service
    from services.audit_service import log_event
    db = _db()
    firm_id = current_user.get("firm_id")
    row = itc_04_service.record_return(
        db, firm_id, payload.client_id, challan_id, payload.model_dump(),
        current_user.get("id"))
    log_event(firm_id or "", "delivery_challan_return", str(row.get("id") or ""),
              "create", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data=row)
    return api_response(True, row)


@router.post("/challans/{challan_id}/issue")
def issue_challan(
    challan_id: str,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """Issue a draft challan: the goods leave on it (POST-A-398).

    The one door that makes a challan `issued`. Issuing records that the goods left on the challan's own date: any period under the Act (s.143 for job work, s.31(7) for goods on approval) is
    run from that date, a job-work challan becomes a row of FORM GST ITC-04, the goods count as delivered against the order it names, and goods can come back on it. It asks that the challan
    is a draft with goods on it, dated no later than today, that Rule 55(1) has every particular it requires of this challan, for job work what is sent, and that its goods are not more than
    its order has undelivered; each refusal is a sentence, and nothing is written before them. Prepare-only: nothing is transmitted to a portal.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    from services.audit_service import log_event
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"id": challan_id, "status": "issued"})
    db = _db()
    firm_id = current_user.get("firm_id")
    svc.row_of_client(db, "delivery_challans", firm_id, challan_id, client_id, "delivery challan")
    row = svc.issue_challan(db, firm_id, challan_id, client_id=client_id, consigner=svc.consigner_of(db, firm_id, client_id))
    log_event(firm_id or "", "delivery_challan_issue", str(row.get("id") or ""),
              "update", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"), new_data={"id": row.get("id"), "document_no": row.get("document_no"), "status": row.get("status")})
    return api_response(True, row)


@router.patch("/challans/{challan_id}")
def update_challan(
    challan_id: str,
    payload: DeliveryChallanUpdateIn,
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """Amend a challan.

    `received_back_on` and the status "received back" are the two fields here
    that change what is OWED: a challan carrying either is no longer running
    towards a deemed supply under s.143(3)/(4), so the service refuses the
    status without the day, either on a cancelled challan, and a day before a
    lot of goods already returned (POST-A-383). A challan that has been issued
    or cancelled keeps what it was made as: its number, date, consignee and
    inter-State flag are not changed (a 409 saying to cancel it and make a
    new one), and neither is its place of supply unless it is a job-work
    challan whose goods are out, where that is the job worker's State
    (POST-A-416). What the API leaves open on it is the transporter, the
    vehicle, the notes, the extension under s.143(1) and the kind of goods;
    the screens write only the back day and the job worker's State.

    THE STATUS IT MAY GIVE IS A TABLE (POST-A-398, `delivery_challan.AMENDMENT_MAY_MAKE`): a draft
    may be cancelled; an issued challan may be received back (with the day) or cancelled, and a
    cancel is refused once a lot is recorded against it on FORM GST ITC-04; a challan whose goods
    are back, or that is cancelled, is at its end. `issued` is never given here: a draft is made
    issued by `POST /challans/{id}/issue`, the one door that records that the goods left. An
    issued (or received-back) challan is not amended into what issuing would have refused
    (a job-work challan keeps what it sends and an inter-State movement a place of supply).
    """
    from services.audit_service import log_event
    assert_client_access(current_user, client_id)
    if _mock():
        return api_response(True, {"id": challan_id,
                                   "received_back_on": payload.received_back_on,
                                   "status": payload.status or "draft"})
    firm_id = current_user.get("firm_id")
    before = svc.row_of_client(_db(), "delivery_challans", firm_id, challan_id, client_id, "delivery challan")
    sent = payload.model_dump()
    row = svc.update_challan(_db(), firm_id, challan_id, sent)
    # What was amended is recorded (POST-A-398): a cancel, a back day, a moved date or a changed kind of goods changes what is owed on a return, and until now left no trace. The fields that
    # decide a period are recorded as they were and as they are; of every other field only its NAME is, never the value of a consignee.
    deciding = ("status", "document_date", "received_back_on", "goods_kind", "extended_to", "place_of_supply")
    log_event(firm_id or "", "delivery_challan_update", str(row.get("id") or challan_id),
              "update", actor_id=current_user.get("auth_user_id"),
              actor_email=current_user.get("email"),
              old_data={k: before.get(k) for k in deciding},
              new_data={"id": row.get("id") or challan_id, "document_no": row.get("document_no"), **{k: row.get(k) for k in deciding},
                        "fields": sorted(k for k, v in sent.items() if v is not None and k != "lines"),
                        # the lines corrected (POST-A-417) are named by id, never by what they now say
                        "lines_corrected": [str(f.get("id")) for f in (sent.get("lines") or []) if isinstance(f, dict)]})
    return api_response(True, row)
