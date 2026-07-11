"""Purchase bills — vendor bills with GST computation and TDS auto-deduction.
IT Act Section 194C: TDS on contractor payments.
IT Act Section 194I: TDS on rent.
IT Act Section 194J: TDS on professional/technical fees.
# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
import os
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError as PydanticValidationError
from models.common import api_response
from models.invoices import PurchaseBillIn, PurchaseBillUpdateIn, BillFromDocumentIn
from core.permissions import rbac
from services.audit_service import log_event
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service

# IT Act §194C: 2% (companies/firms); §194I: 10%; §194J: 10%
# Default rates when vendor master tds_rate_bps is 0
_TDS_DEFAULT_BPS: dict[str, int] = {
    "194C":  200,   # 2% for companies/firms (conservative default)
    "194I":  1000,  # 10% on rent
    "194IA": 100,   # 1% on immovable property transfer
    "194J":  1000,  # 10% professional/technical fees
    "194H":  500,   # 5% commission/brokerage
    "194A":  1000,  # 10% interest (other than bank)
}

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.purchase_bills")


def _current_fy_long() -> str:
    """Return full financial year string like '2025-26' for display/timeline use.
    Indian FY runs April 1 – March 31.
    """
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def _fy_bounds(date_str: str) -> tuple[str, str]:
    """Return (fy_start_iso, fy_end_iso) for the Indian FY containing date_str.
    Used to aggregate a vendor's prior taxable for TDS thresholds. Apr 1 – Mar 31."""
    d = datetime.strptime(str(date_str)[:10], "%Y-%m-%d").date()
    start = d.year if d.month >= 4 else d.year - 1
    return f"{start}-04-01", f"{start + 1}-03-31"

router = APIRouter(prefix="/api/purchase-bills", tags=["purchase_bills"])

# ---------------------------------------------------------------------------
# Mock stores
# ---------------------------------------------------------------------------
MOCK_PURCHASE_BILLS: list[dict] = []
MOCK_PURCHASE_BILL_LINES: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _compute_line_gst(
    taxable_paise: int,
    gst_rate_bps: int,
    is_interstate: bool,
) -> tuple[int, int, int]:
    """
    Compute CGST, SGST, IGST in integer paise.
    CGST Act §8: Intra-state → CGST+SGST; Inter-state → IGST.
    """
    if is_interstate:
        igst = (taxable_paise * gst_rate_bps) // 10000
        return 0, 0, igst
    half_rate = gst_rate_bps // 2
    cgst = (taxable_paise * half_rate) // 10000
    sgst = (taxable_paise * half_rate) // 10000
    return cgst, sgst, 0


def _get_state_code_from_gstin(gstin: Optional[str]) -> Optional[str]:
    if gstin and len(gstin) >= 2:
        return gstin[:2]
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_purchase_bills(
    client_id: str = Query(..., description="CA client ID — required"),
    vendor_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, description="Filter by bill_date >= from_date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Filter by bill_date <= to_date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List purchase bills with optional filters."""
    try:
        if _USE_MOCK:
            result = [b for b in MOCK_PURCHASE_BILLS if b["client_id"] == client_id]
            if vendor_id:
                result = [b for b in result if b.get("vendor_id") == vendor_id]
            if status:
                result = [b for b in result if b.get("status") == status]
            if from_date:
                result = [b for b in result if b.get("bill_date", "") >= from_date]
            if to_date:
                result = [b for b in result if b.get("bill_date", "") <= to_date]
            result = result[offset:offset + limit]
            return api_response(True, result)

        from core.supabase_client import get_supabase
        db = get_supabase()
        q = db.table("purchase_bills").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id)
        if vendor_id:
            q = q.eq("vendor_id", vendor_id)
        if status:
            q = q.eq("status", status)
        if from_date:
            q = q.gte("bill_date", from_date)
        if to_date:
            q = q.lte("bill_date", to_date)
        resp = q.order("bill_date", desc=True).range(offset, offset + limit - 1).execute()
        return api_response(True, resp.data or [])
    except Exception as e:
        _logger.error("list_purchase_bills: %s", e)
        return api_response(False, None, "Unable to complete purchase bill operation. Please try again.")


@router.post("/")
def create_purchase_bill(
    data: PurchaseBillIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Create a purchase bill with automatic GST computation and TDS deduction.
    IT Act §194C/194I/194J: TDS rates sourced from vendor master.
    All monetary values in integer paise. Status: 'draft'.
    """
    try:
        bill = _create_purchase_bill_core(data.model_dump(), current_user)
        return api_response(True, bill)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_purchase_bill: %s", e)
        return api_response(False, None, "Unable to create purchase bill. Please try again.")


def _create_purchase_bill_core(data: dict, current_user: dict) -> dict:
    """Shared purchase-bill-creation logic used by both create_purchase_bill
    and the bulk import endpoint below — extracted verbatim (no behavior
    change) so the CSV importer can create many bills in ONE request instead
    of firing one POST per bill. Raises HTTPException on failure; returns the
    created bill dict (with lines) on success."""
    required = ["client_id", "vendor_id", "bill_date", "lines"]
    for field in required:
        if not data.get(field):
            raise HTTPException(status_code=422, detail=f"{field} is required")

    firm_id   = current_user.get("firm_id")
    client_id = data["client_id"]
    vendor_id = data["vendor_id"]
    lines_data = data.get("lines", [])
    if not lines_data:
        raise HTTPException(status_code=422, detail="At least one line item is required")

    if _USE_MOCK:
        # Look up vendor from in-memory store; fall back to safe defaults
        from routers.vendors import MOCK_VENDORS
        vendor = next((v for v in MOCK_VENDORS if v.get("id") == vendor_id), None)
        if vendor is None:
            vendor = {"tds_applicable": False, "tds_section": None, "tds_rate_bps": 0, "state_code": "27"}
        is_interstate = False
    else:
        from core.supabase_client import get_supabase
        db = get_supabase()

        # Fetch vendor for TDS info and state code (firm-scoped — tenant isolation)
        v_resp = db.table("vendors").select("*").eq("id", vendor_id).eq("firm_id", firm_id).limit(1).execute()
        if not v_resp.data:
            raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
        vendor = v_resp.data[0]
        # Business guard: never book a bill against a deactivated vendor.
        if vendor.get("is_active") is False:
            raise HTTPException(status_code=422, detail="This vendor is inactive. Reactivate the vendor before booking a bill.")

        # Determine is_interstate
        vendor_state = vendor.get("state_code") or _get_state_code_from_gstin(vendor.get("gstin")) or ""
        client_resp  = db.table("clients").select("gstin").eq("id", client_id).eq("firm_id", firm_id).limit(1).execute()
        client_state = ""
        if client_resp.data:
            client_state = _get_state_code_from_gstin(client_resp.data[0].get("gstin")) or ""
        is_interstate = bool(vendor_state and client_state and vendor_state != client_state)

    # Compute lines — all in integer paise
    computed_lines: list[dict] = []
    total_taxable = 0
    total_cgst    = 0
    total_sgst    = 0
    total_igst    = 0

    for ln in lines_data:
        qty          = ln.get("quantity", 1)
        rate_paise   = int(ln.get("rate_paise", 0))
        # Model uses gst_rate_percent (e.g. 18.0), convert to bps (10000 bps = 100%)
        gst_rate_percent = float(ln.get("gst_rate_percent", 0) or ln.get("gst_rate_bps", 0) / 100)
        gst_rate_bps = int(round(gst_rate_percent * 100))
        taxable      = int(Decimal(str(qty)) * rate_paise)
        cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, is_interstate)

        total_taxable += taxable
        total_cgst    += cgst
        total_sgst    += sgst
        total_igst    += igst

        computed_lines.append({
            "description":          ln.get("description", ""),
            "hsn_sac":              ln.get("hsn_sac", ""),
            "expense_account_id":   ln.get("expense_account_id"),
            "quantity":             qty,
            "unit":                 ln.get("unit") or "NOS",
            "rate_paise":           rate_paise,
            "gst_rate_bps":         gst_rate_bps,
            "taxable_amount_paise": taxable,
            "cgst_paise":           cgst,
            "sgst_paise":           sgst,
            "igst_paise":           igst,
            "line_total_paise":     taxable + cgst + sgst + igst,
            "service_catalogue_id": ln.get("service_catalogue_id"),
        })

    total_paise = total_taxable + total_cgst + total_sgst + total_igst

    # ── Multi-Currency (Phase 3): resolve + freeze the bill currency ──────────
    # INR / feature-off → identity. For a foreign bill the line totals above are
    # in the txn currency's minor units; convert each to base (INR) paise (sum =
    # base total, exact GL balance) BEFORE TDS, because statutory TDS is always
    # computed on the INR-equivalent taxable.
    from domain.currency.document_currency import resolve_document_currency, identity_currency
    req_ccy = (data.get("currency") or "INR").strip().upper()
    if _USE_MOCK or req_ccy == "INR":
        dc = identity_currency(data["bill_date"])
    else:
        _firm_row = (db.table("firms").select("multi_currency_entitled").eq("id", firm_id).limit(1).execute().data or [None])[0]
        _client_mc = (db.table("clients").select("functional_currency, multi_currency_enabled").eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0]
        dc = resolve_document_currency(
            db, _firm_row, _client_mc, currency=req_ccy,
            exchange_rate=data.get("exchange_rate"), rate_date=data["bill_date"],
            rate_selected_by=current_user.get("id"))

    txn_taxable   = total_taxable
    txn_total_gst = total_cgst + total_sgst + total_igst
    txn_total     = txn_taxable + txn_total_gst
    total_taxable = dc.to_base(total_taxable)
    total_cgst    = dc.to_base(total_cgst)
    total_sgst    = dc.to_base(total_sgst)
    total_igst    = dc.to_base(total_igst)
    total_paise   = total_taxable + total_cgst + total_sgst + total_igst

    # ── TDS — routed through the central engine (domain/tds/tds_computer).
    # No inline rate maths: the engine owns thresholds, FY aggregation, payee-type
    # rates, unknown-section handling and the rate bound (audit H5/H6/L1/L6).
    # TDS base is the taxable amount, excluding GST — IT Act §194C/194I/194J.
    is_reverse_charge = bool(data.get("is_reverse_charge", False))
    tds_paise = 0
    tds_rate_bps = 0
    tds_section = (vendor.get("tds_section") or "").upper().strip() or None
    if vendor.get("tds_applicable"):
        if not tds_section:
            raise HTTPException(
                status_code=422,
                detail="Vendor is marked TDS-applicable but has no TDS section set.",
            )
        from domain.tds.tds_computer import TDSComputer, is_company_pan, has_pan
        # FY-aggregate of this vendor's prior taxable under the same section, so the
        # §194C ₹1L aggregate threshold is honoured across multiple bills.
        fy_prior = 0
        if not _USE_MOCK:
            fy_start, fy_end = _fy_bounds(data["bill_date"])
            prior = (db.table("purchase_bills")
                     .select("taxable_amount_paise")
                     .eq("firm_id", firm_id).eq("vendor_id", vendor_id)
                     .eq("tds_section", tds_section).neq("status", "cancelled")
                     .gte("bill_date", fy_start).lte("bill_date", fy_end)
                     .execute().data) or []
            fy_prior = sum(int(b.get("taxable_amount_paise") or 0) for b in prior)
        # Resolve thresholds/rates for the FY the BILL falls in, not "today" —
        # a bill entered late for a prior FY must use that year's law.
        try:
            _bill_d = datetime.strptime(str(data["bill_date"])[:10], "%Y-%m-%d").date()
            _fy_start_year = _bill_d.year if _bill_d.month >= 4 else _bill_d.year - 1
            bill_fy = f"{_fy_start_year}-{str(_fy_start_year + 1)[2:]}"
        except (ValueError, KeyError):
            bill_fy = None  # malformed/missing date → registry defaults to current FY
        try:
            _tds = TDSComputer().resolve_tds(
                section=tds_section,
                taxable_paise=total_taxable,
                fy_prior_taxable_paise=fy_prior,
                is_company=is_company_pan(vendor.get("pan")),
                fy=bill_fy,
                # IT Act §206AA: no real PAN on file floors the rate at
                # 20% (R3.10) — previously computed with zero PAN
                # awareness, silently under-deducting for no-PAN vendors.
                has_pan=has_pan(vendor.get("pan")),
            )
        except ValueError as ve:
            raise HTTPException(status_code=422, detail=str(ve))
        tds_paise = _tds.tds_paise
        # Persist the rate ACTUALLY applied — 0 when below threshold (nothing
        # deducted), the section/payee rate when TDS was deducted (H6, §203 audit).
        tds_rate_bps = _tds.rate_bps if _tds.applies else 0

    net_payable_paise = total_paise - tds_paise
    total_gst_paise = total_cgst + total_sgst + total_igst   # M1: persist on the bill

    # Currency columns (INR identity leaves them inert). Foreign net payable is
    # the foreign total less TDS expressed in the txn currency at the frozen rate.
    _ccy_cols = {
        "txn_currency":     dc.currency,
        "exchange_rate":    str(dc.rate),
        "txn_taxable":      txn_taxable,
        "txn_total_gst":    txn_total_gst,
        "txn_total":        txn_total,
        "txn_net_payable":  txn_total - dc.to_txn(tds_paise),
        "rate_source":      dc.rate_source,
        "rate_type":        dc.rate_type,
        "rate_date":        dc.rate_date,
        "rate_selected_by": dc.rate_selected_by,
        "rate_overridden":  dc.rate_overridden,
    }

    # Validate posting date is not in a locked financial year (migration 020)
    period_validation_service.validate_posting_date(firm_id or "", data["bill_date"])

    if _USE_MOCK:
        bill_id = str(uuid.uuid4())
        bill = {
            "id":                    bill_id,
            "firm_id":               firm_id,
            "client_id":             client_id,
            "vendor_id":             vendor_id,
            "bill_no":               data.get("bill_no", ""),
            "our_reference":         data.get("our_reference"),
            "bill_date":             data["bill_date"],
            "due_date":              data.get("due_date"),
            "is_interstate":         is_interstate,
            "taxable_amount_paise":  total_taxable,
            "cgst_paise":            total_cgst,
            "sgst_paise":            total_sgst,
            "igst_paise":            total_igst,
            "total_paise":           total_paise,
            "total_gst_paise":       total_gst_paise,
            "tds_paise":             tds_paise,
            "tds_rate_bps":          tds_rate_bps,
            "tds_section":           tds_section,
            "is_reverse_charge":     is_reverse_charge,
            "net_payable_paise":     net_payable_paise,
            "status":                "draft",
            "notes":                 data.get("notes", ""),
            "created_at":            datetime.now(timezone.utc).isoformat(),
            **_ccy_cols,
            "lines":                 computed_lines,
        }
        MOCK_PURCHASE_BILLS.append(bill)
        for ln in computed_lines:
            ln["id"]      = str(uuid.uuid4())
            ln["bill_id"] = bill_id
            MOCK_PURCHASE_BILL_LINES.append(ln)
        return bill

    bill_payload = {
        "firm_id":               firm_id,
        "client_id":             client_id,
        "vendor_id":             vendor_id,
        "bill_no":               data.get("bill_no", ""),
        "our_reference":         data.get("our_reference"),
        "bill_date":             data["bill_date"],
        "due_date":              data.get("due_date"),
        "is_interstate":         is_interstate,
        "taxable_amount_paise":  total_taxable,
        "cgst_paise":            total_cgst,
        "sgst_paise":            total_sgst,
        "igst_paise":            total_igst,
        "total_paise":           total_paise,
        "total_gst_paise":       total_gst_paise,
        "tds_paise":             tds_paise,
        "tds_rate_bps":          tds_rate_bps,
        "tds_section":           tds_section,
        "is_reverse_charge":     is_reverse_charge,
        "net_payable_paise":     net_payable_paise,
        "status":                "draft",
        "notes":                 data.get("notes", ""),
        "created_at":            datetime.now(timezone.utc).isoformat(),
        **_ccy_cols,
    }

    bill_resp = db.table("purchase_bills").insert(bill_payload).execute()  # type: ignore[possibly-undefined]
    bill      = bill_resp.data[0] if bill_resp.data else bill_payload
    bill_id   = bill.get("id", str(uuid.uuid4()))

    line_payloads = [
        {
            "bill_id":               bill_id,
            "description":           ln["description"],
            "hsn_sac":               ln["hsn_sac"],
            "expense_account_id":    ln.get("expense_account_id"),
            "quantity":              ln["quantity"],
            "unit":                  ln.get("unit") or "NOS",
            "rate_paise":            ln["rate_paise"],
            "gst_rate_bps":          ln["gst_rate_bps"],
            "taxable_amount_paise":  ln["taxable_amount_paise"],
            "cgst_paise":            ln["cgst_paise"],
            "sgst_paise":            ln["sgst_paise"],
            "igst_paise":            ln["igst_paise"],
            "line_total_paise":      ln["line_total_paise"],
            # BUG FIX (audit): this key was missing entirely, so a product
            # picked via ServiceCataloguePicker on a Purchase Bill line never
            # actually persisted — apply_purchase_to_inventory's later SELECT
            # of this column always saw NULL, silently skipping stock-in for
            # every bill ever created through this path.
            "service_catalogue_id":  ln.get("service_catalogue_id"),
        }
        for ln in computed_lines
    ]
    lines_resp = db.table("purchase_bill_lines").insert(line_payloads).execute()  # type: ignore[possibly-undefined]
    bill["lines"] = lines_resp.data or computed_lines

    log_event(
        firm_id or "", "purchase_bill", bill_id,
        "create", actor_id=current_user.get("auth_user_id"),
        actor_email=current_user.get("email"), new_data=bill,
    )
    timeline_service.log(
        client_id, "accounting", "Purchase Bill Created",
        f"Bill {bill.get('bill_no', '')} for ₹{bill.get('total_paise', 0) // 100:,} created (draft)",
        "info", firm_id=firm_id or "",
        entity_type="purchase_bill", entity_id=bill_id,
        amount_paise=bill.get("total_paise"), actor_id=current_user.get("auth_user_id"),
    )
    return bill


class _BulkPurchaseBillsIn(BaseModel):
    bills: list[dict]


@router.post("/bulk")
def bulk_create_purchase_bills(
    payload: _BulkPurchaseBillsIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Create many purchase bills in ONE request.

    The CSV importer used to fire one POST /api/purchase-bills/ per bill — for
    a 100-row import that's 100 sequential network round-trips, and it
    multiplies badly when many firms import concurrently. This endpoint loops
    the exact same _create_purchase_bill_core logic server-side (no behavior
    change, no duplicated GST/TDS business rules), so N round-trips collapse
    to 1. A bad row is reported per-item and does not abort the rest of the
    batch — matches the existing CSV-import UX (partial success with a
    per-row error list).
    """
    items = payload.bills
    created: list[dict] = []
    errors: list[dict] = []
    for i, raw in enumerate(items):
        bill_no = raw.get("bill_no", "") if isinstance(raw, dict) else ""
        try:
            try:
                data = PurchaseBillIn(**raw)
            except PydanticValidationError as e:
                errors.append({"index": i, "bill_no": bill_no, "error": str(e.errors()[0].get("msg", "Invalid bill data")) if e.errors() else "Invalid bill data"})
                continue
            bill = _create_purchase_bill_core(data.model_dump(), current_user)
            created.append(bill)
        except HTTPException as e:
            errors.append({"index": i, "bill_no": bill_no, "error": e.detail})
        except Exception as e:
            _logger.error("bulk_create_purchase_bills item %d failed: %s", i, e, exc_info=True)
            errors.append({"index": i, "bill_no": bill_no, "error": "Unable to create this bill. Please try again."})
    return api_response(True, {"created": created, "errors": errors})


@router.get("/{bill_id}")
def get_purchase_bill(
    bill_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Get a purchase bill with line items."""
    try:
        if _USE_MOCK:
            bill = next((b for b in MOCK_PURCHASE_BILLS if b["id"] == bill_id), None)
            if not bill:
                raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
            bill["lines"] = [ln for ln in MOCK_PURCHASE_BILL_LINES if ln.get("bill_id") == bill_id]
            return api_response(True, bill)

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("purchase_bills").select("*").eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
        bill = resp.data[0]
        lines_resp = db.table("purchase_bill_lines").select("*").eq("bill_id", bill_id).execute()
        bill["lines"] = lines_resp.data or []
        return api_response(True, bill)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_purchase_bill: %s", e)
        return api_response(False, None, "Unable to complete purchase bill operation. Please try again.")


# Once a bill is received, only these fields may still change — mirrors the
# same rule on sales invoices (routers/sales_invoices.py:_SOFT_UPDATE_FIELDS).
# line_units is handled separately, always allowed regardless of status.
_SOFT_BILL_UPDATE_FIELDS = {"notes", "due_date", "our_reference"}


def _reject_locked_bill_fields(data: dict) -> None:
    """bill_no/bill_date/lines/is_inter_state are locked once a bill is
    received — a correction to any of those needs a Debit Note instead of a
    silent edit (CGST Act §34, same principle as the sales-invoice side)."""
    locked = sorted(set(data.keys()) - _SOFT_BILL_UPDATE_FIELDS)
    if locked:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot change {', '.join(locked)} on a received bill — only "
                "our reference, notes and due date can still be edited. Issue "
                "a Debit Note to correct anything else (CGST Act §34)."
            ),
        )


@router.patch("/{bill_id}")
def update_purchase_bill(
    bill_id: str,
    data: PurchaseBillUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Update a purchase bill. DRAFT: full edit. RECEIVED/PARTIALLY_PAID/
    PAID: only our_reference, notes, due_date and line_units may change —
    see _reject_locked_bill_fields. CANCELLED: cannot be updated at all."""
    try:
        data = data.model_dump(exclude_none=True)
        # Always allowed regardless of status — unit alone never touches
        # rate/quantity/amount/GST.
        line_units = data.pop("line_units", None)

        if _USE_MOCK:
            for i, b in enumerate(MOCK_PURCHASE_BILLS):
                if b["id"] == bill_id:
                    status = b.get("status")
                    if status == "cancelled":
                        raise HTTPException(status_code=422, detail="Cancelled bills cannot be updated")
                    if status != "draft":
                        _reject_locked_bill_fields(data)
                    if line_units:
                        for ln in MOCK_PURCHASE_BILL_LINES:
                            if ln.get("id") in line_units and ln.get("bill_id") == bill_id:
                                ln["unit"] = line_units[ln["id"]] or "NOS"
                    MOCK_PURCHASE_BILLS[i] = {**b, **data, "updated_at": datetime.now(timezone.utc).isoformat()}
                    return api_response(True, MOCK_PURCHASE_BILLS[i])
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        # Tenant isolation (OOS-5): firm-scope the guard read and the write so a
        # foreign-firm bill id cannot be read or mutated under service-role.
        resp = db.table("purchase_bills").select("status, bill_date").eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
        status = resp.data[0]["status"]
        if status == "cancelled":
            raise HTTPException(status_code=422, detail="Cancelled bills cannot be updated")
        if status != "draft":
            _reject_locked_bill_fields(data)
        # FY-lock: block editing a bill dated in a locked year, and block moving it
        # INTO a locked year. (Create already validates; edits were the gap.)
        firm_id = current_user.get("firm_id") or ""
        existing_date = resp.data[0].get("bill_date")
        if existing_date:
            period_validation_service.validate_posting_date(firm_id, existing_date)
        if data.get("bill_date"):
            period_validation_service.validate_posting_date(firm_id, data["bill_date"])

        # Per-line unit correction — safe on any non-cancelled status since
        # unit never affects rate/quantity/amount/GST.
        if line_units:
            for line_id, unit in line_units.items():
                db.table("purchase_bill_lines").update(
                    {"unit": unit or "NOS"}
                ).eq("id", line_id).eq("bill_id", bill_id).execute()

        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        upd = db.table("purchase_bills").update(data).eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).execute()
        updated = upd.data[0] if upd.data else data
        log_event(
            current_user.get("firm_id", ""), "purchase_bill", bill_id,
            "update", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=updated,
        )
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_purchase_bill: %s", e)
        return api_response(False, None, "Unable to complete purchase bill operation. Please try again.")


@router.post("/{bill_id}/receive")
def receive_purchase_bill(
    bill_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Transition purchase bill draft → received.
    Auto-creates journal entry via Phase2JournalService.
    IT Act §194C/194I/194J: Journal records TDS payable.
    """
    try:
        from services.phase2_journal_service import phase2_journal_service

        if _USE_MOCK:
            for i, b in enumerate(MOCK_PURCHASE_BILLS):
                if b["id"] == bill_id:
                    if b.get("status") != "draft":
                        raise HTTPException(status_code=422, detail="Only draft bills can be received")
                    MOCK_PURCHASE_BILLS[i]["status"]      = "received"
                    MOCK_PURCHASE_BILLS[i]["received_at"] = datetime.now(timezone.utc).isoformat()
                    phase2_journal_service.journal_for_purchase_bill(
                        MOCK_PURCHASE_BILLS[i],
                        current_user.get("firm_id", ""),
                        MOCK_PURCHASE_BILLS[i]["client_id"],
                    )
                    return api_response(True, MOCK_PURCHASE_BILLS[i])
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        # Tenant isolation (OOS-5): firm-scope the guard read and the write so a
        # foreign-firm bill id cannot be read or mutated under service-role.
        resp = db.table("purchase_bills").select("*").eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
        bill = resp.data[0]
        if bill.get("status") != "draft":
            raise HTTPException(status_code=422, detail="Only draft bills can be received")
        # FY-lock: receiving posts a dated journal — block if the year was locked
        # after the draft was created (deferred-posting gap).
        if bill.get("bill_date"):
            period_validation_service.validate_posting_date(current_user.get("firm_id") or "", bill["bill_date"])

        now_iso = datetime.now(timezone.utc).isoformat()
        upd = db.table("purchase_bills").update({
            "status":      "received",
            "received_at": now_iso,
        }).eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).execute()
        updated_bill = upd.data[0] if upd.data else {**bill, "status": "received"}

        journal_id = phase2_journal_service.journal_for_purchase_bill(
            bill=updated_bill,
            firm_id=current_user.get("firm_id", ""),
            client_id=updated_bill.get("client_id", ""),
        )
        # Persist the journal link so cancellation can reverse it directly.
        if journal_id:
            db.table("purchase_bills").update({"journal_entry_id": journal_id}).eq(
                "id", bill_id).eq("firm_id", current_user.get("firm_id")).execute()

        log_event(
            current_user.get("firm_id", ""), "purchase_bill", bill_id,
            "status_change", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"status": "received", "journal_entry_id": journal_id},
        )
        # Record timeline event for received/posted bill
        timeline_service.log_timeline_event(
            client_id=updated_bill.get("client_id", ""),
            firm_id=current_user.get("firm_id", ""),
            financial_year=_current_fy_long(),
            category="accounting",
            event_type="bill_posted",
            title=f"Purchase Bill {updated_bill.get('bill_no', bill_id)} posted",
            description=f"Vendor bill for ₹{updated_bill.get('total_paise', 0) // 100:,} received.",
            severity="success",
            entity_type="purchase_bill",
            entity_id=bill_id,
            amount_paise=updated_bill.get("total_paise"),
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )

        # Inventory: stock-in + moving-average recompute for any goods lines
        # linked to a stock-tracked catalogue item, plus a reclassification
        # journal entry moving that value from the expense account it landed
        # on into Inventory. Runs AFTER the bill is committed received — a
        # failure here must never affect an already-received bill.
        # apply_purchase_to_inventory itself never raises; this try/except is
        # belt-and-suspenders.
        try:
            from domain.inventory_service import apply_purchase_to_inventory
            apply_purchase_to_inventory(
                db, firm_id=current_user.get("firm_id", ""), client_id=updated_bill.get("client_id", ""),
                bill=updated_bill, created_by=current_user.get("auth_user_id"),
            )
        except Exception as e:
            _logger.error("receive_purchase_bill: inventory posting failed for %s: %s", bill_id, e, exc_info=True)

        updated_bill["journal_entry_id"] = journal_id
        return api_response(True, updated_bill)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("receive_purchase_bill: %s", e)
        return api_response(False, None, "Unable to complete purchase bill operation. Please try again.")


@router.post("/{bill_id}/cancel")
def cancel_purchase_bill(
    bill_id: str,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Cancel a purchase bill. Requires accounting.approve (Partner only)."""
    try:
        if _USE_MOCK:
            for i, b in enumerate(MOCK_PURCHASE_BILLS):
                if b["id"] == bill_id:
                    if b.get("status") == "cancelled":
                        raise HTTPException(status_code=422, detail="Bill already cancelled")
                    MOCK_PURCHASE_BILLS[i]["status"]       = "cancelled"
                    MOCK_PURCHASE_BILLS[i]["cancelled_at"] = datetime.now(timezone.utc).isoformat()
                    return api_response(True, MOCK_PURCHASE_BILLS[i])
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")

        from core.supabase_client import get_supabase
        from services.phase2_journal_service import phase2_journal_service
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        # Tenant isolation (OOS-5): firm-scope the guard read and the write so a
        # foreign-firm bill id cannot be read or mutated under service-role.
        resp = (db.table("purchase_bills")
                .select("status, journal_entry_id, bill_no, our_reference, client_id, paid_paise")
                .eq("id", bill_id).eq("firm_id", firm_id).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
        bill = resp.data[0]
        status = bill.get("status")
        if status == "cancelled":
            raise HTTPException(status_code=422, detail="Bill already cancelled")
        if status == "draft":
            raise HTTPException(status_code=422, detail="Draft bills are deleted, not cancelled.")
        # Accounting guard: never cancel a bill that has payments — the payment
        # journal would be stranded. Reverse the payment(s) first.
        if int(bill.get("paid_paise") or 0) > 0:
            raise HTTPException(status_code=409, detail="This bill has payments recorded and cannot be cancelled. Reverse the payment(s) first.")
        pay = (db.table("purchase_payments").select("id")
               .eq("firm_id", firm_id).eq("purchase_bill_id", bill_id).limit(1).execute().data)
        if pay:
            raise HTTPException(status_code=409, detail="This bill has payments allocated and cannot be cancelled. Reverse the payment(s) first.")

        # A cancellation reversal is a NEW posting dated today — open FY required.
        reversal_date = datetime.now(timezone.utc).date().isoformat()
        period_validation_service.validate_posting_date(firm_id or "", reversal_date)

        # Locate the bill's posted receive-journal and reverse it THROUGH the kernel
        # (append-only; original untouched). Idempotent on retry.
        jrnl_id = bill.get("journal_entry_id")
        if not jrnl_id:
            jr = (db.table("journal_entries").select("id")
                  .eq("firm_id", firm_id).eq("client_id", bill.get("client_id"))
                  .eq("reference_no", bill.get("bill_no")).eq("entry_type", "Purchase").eq("is_posted", True)
                  .limit(1).execute().data)
            jrnl_id = jr[0]["id"] if jr else None
        if not jrnl_id:
            raise HTTPException(status_code=422, detail="No posted journal found for this bill to reverse.")
        already = (db.table("journal_entries").select("id")
                   .eq("firm_id", firm_id).eq("reversal_of", jrnl_id).limit(1).execute().data)
        if not already:
            phase2_journal_service.reverse_entry(
                db, firm_id, jrnl_id, reversal_date,
                narration=f"Cancellation of purchase bill {bill.get('bill_no') or bill_id}",
                created_by=current_user.get("id"),
            )

        upd = db.table("purchase_bills").update({
            "status":       "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", bill_id).eq("firm_id", firm_id).execute()
        updated = upd.data[0] if upd.data else {}

        # Inventory: undo the stock-in + Inventory-reclass journal
        # apply_purchase_to_inventory posted at receive time, for any goods
        # lines on this bill. Runs AFTER cancellation is committed — never
        # blocks it.
        try:
            from domain.inventory_service import reverse_purchase_stock
            reverse_purchase_stock(
                db, firm_id=firm_id or "", client_id=bill.get("client_id", ""), bill_id=bill_id,
                bill_reference=bill.get("bill_no") or bill.get("our_reference") or bill_id,
                created_by=current_user.get("auth_user_id"),
            )
        except Exception as e:
            _logger.error("cancel_purchase_bill: inventory reversal failed for %s: %s", bill_id, e, exc_info=True)

        log_event(
            firm_id or "", "purchase_bill", bill_id,
            "cancel", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"status": "cancelled", "reversed_journal": jrnl_id},
        )
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("cancel_purchase_bill: %s", e)
        return api_response(False, None, "Unable to complete purchase bill operation. Please try again.")


@router.post("/from-document")
def create_bill_from_document(
    data: BillFromDocumentIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Create a draft purchase bill from AI-extracted document data.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    Human must call /receive to post the bill — never auto-posted.
    Status is always 'draft' regardless of extraction confidence.
    """
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    try:
        client_id      = data.client_id
        extracted_data = data.extracted_data
        firm_id        = current_user.get("firm_id")

        if not client_id:
            raise HTTPException(status_code=422, detail="client_id is required")
        if not extracted_data:
            raise HTTPException(status_code=422, detail="extracted_data is required")

        vendor_id = None

        if _USE_MOCK:
            # Try to match vendor by GSTIN or name
            vendor_gstin = extracted_data.get("gstin") or extracted_data.get("vendor_gstin")
            vendor_name  = extracted_data.get("vendor_name", "")
            for v in []:  # mock vendor list
                if vendor_gstin and v.get("gstin") == vendor_gstin:
                    vendor_id = v["id"]
                    break
                if vendor_name and vendor_name.lower() in str(v.get("name", "")).lower():
                    vendor_id = v["id"]
                    break
        else:
            from core.supabase_client import get_supabase
            db = get_supabase()
            vendor_gstin = extracted_data.get("gstin") or extracted_data.get("vendor_gstin")
            vendor_name  = extracted_data.get("vendor_name", "")

            if vendor_gstin:
                v_resp = (
                    db.table("vendors")
                    .select("id")
                    .eq("firm_id", firm_id)
                    .eq("client_id", client_id)
                    .eq("gstin", vendor_gstin)
                    .limit(1)
                    .execute()
                )
                if v_resp.data:
                    vendor_id = v_resp.data[0]["id"]

            if not vendor_id and vendor_name:
                v_resp = (
                    db.table("vendors")
                    .select("id")
                    .eq("firm_id", firm_id)
                    .eq("client_id", client_id)
                    .ilike("name", f"%{vendor_name}%")
                    .limit(1)
                    .execute()
                )
                if v_resp.data:
                    vendor_id = v_resp.data[0]["id"]

        bill_id    = str(uuid.uuid4())
        now_iso    = datetime.now(timezone.utc).isoformat()
        bill_draft = {
            "id":                   bill_id,
            "firm_id":              firm_id,
            "client_id":            client_id,
            "vendor_id":            vendor_id,
            "bill_no":              extracted_data.get("invoice_no", ""),
            "bill_date":            extracted_data.get("invoice_date", ""),
            "taxable_amount_paise": int(extracted_data.get("taxable_amount_paise", 0)),
            "cgst_paise":           int(extracted_data.get("cgst_paise", 0)),
            "sgst_paise":           int(extracted_data.get("sgst_paise", 0)),
            "igst_paise":           int(extracted_data.get("igst_paise", 0)),
            "total_paise":          int(extracted_data.get("total_paise", 0)),
            "tds_paise":            0,  # TDS requires CA review before application
            "net_payable_paise":    int(extracted_data.get("total_paise", 0)),
            "is_ai_extracted":      True,
            "ai_extraction_data":   extracted_data,
            "status":               "draft",  # NEVER auto-receive — CA REVIEW REQUIRED
            "created_at":           now_iso,
        }

        if _USE_MOCK:
            MOCK_PURCHASE_BILLS.append(bill_draft)
            return api_response(True, {**bill_draft, "requires_review": True})

        pb_resp = db.table("purchase_bills").insert(bill_draft).execute()  # type: ignore[possibly-undefined]
        bill    = pb_resp.data[0] if pb_resp.data else bill_draft

        # Insert line items if provided
        line_items = extracted_data.get("line_items", [])
        if line_items:
            line_payloads = [
                {
                    "bill_id":              bill.get("id", bill_id),
                    "description":          ln.get("description", ""),
                    "hsn_sac":              ln.get("hsn_sac", ""),
                    "rate_paise":           int(ln.get("rate_paise", 0)),
                    "unit":                 ln.get("unit") or "NOS",
                    "gst_rate_bps":         int(ln.get("gst_rate_bps", 0)),
                    "quantity":             ln.get("quantity", 1),
                    "taxable_amount_paise": int(ln.get("taxable_amount_paise", 0)),
                    "cgst_paise":           0,
                    "sgst_paise":           0,
                    "igst_paise":           0,
                    "line_total_paise":     int(ln.get("rate_paise", 0)),
                    # AI extraction has no product-catalogue awareness — the CA
                    # links a Product/Service later via the draft's line editor.
                }
                for ln in line_items
            ]
            db.table("purchase_bill_lines").insert(line_payloads).execute()  # type: ignore[possibly-undefined]

        log_event(
            firm_id or "", "purchase_bill", bill.get("id", bill_id),
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data=bill,
            metadata={"source": "ai_extraction", "requires_review": True},
        )
        # Separate audit event for document_extraction action — tracks AI extraction usage
        log_event(
            firm_id or "", "purchase_bill", bill.get("id", bill_id),
            "document_extraction", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            metadata={
                "vendor_gstin": extracted_data.get("vendor_gstin"),
                "invoice_no":   extracted_data.get("invoice_no"),
                "requires_review": True,
            },
        )
        return api_response(True, {**bill, "requires_review": True})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_bill_from_document: %s", e)
        return api_response(False, None, "Unable to complete purchase bill operation. Please try again.")
