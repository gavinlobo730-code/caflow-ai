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
        data = data.model_dump()
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

            # Fetch vendor for TDS info and state code
            v_resp = db.table("vendors").select("*").eq("id", vendor_id).limit(1).execute()
            if not v_resp.data:
                raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
            vendor = v_resp.data[0]

            # Determine is_interstate
            vendor_state = vendor.get("state_code") or _get_state_code_from_gstin(vendor.get("gstin")) or ""
            client_resp  = db.table("clients").select("gstin").eq("id", client_id).limit(1).execute()
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
                "rate_paise":           rate_paise,
                "gst_rate_bps":         gst_rate_bps,
                "taxable_amount_paise": taxable,
                "cgst_paise":           cgst,
                "sgst_paise":           sgst,
                "igst_paise":           igst,
                "line_total_paise":     taxable + cgst + sgst + igst,
            })

        total_paise = total_taxable + total_cgst + total_sgst + total_igst

        # TDS computation — integer paise, never float
        # IT Act §194C: 2% (companies/firms); §194I: 10%; §194J: 10%
        tds_paise = 0
        if vendor.get("tds_applicable"):
            tds_rate_bps = int(vendor.get("tds_rate_bps") or 0)
            if tds_rate_bps == 0 and vendor.get("tds_section"):
                # Auto-populate statutory default when vendor master rate not set
                section = str(vendor["tds_section"]).upper().strip()
                tds_rate_bps = _TDS_DEFAULT_BPS.get(section, 0)
            if tds_rate_bps > 0:
                # TDS is on taxable amount (excluding GST) — IT Act §194C/194I/194J
                tds_paise = (total_taxable * tds_rate_bps) // 10000
                if tds_paise > total_taxable:
                    raise HTTPException(status_code=422, detail="TDS cannot exceed taxable amount")

        net_payable_paise = total_paise - tds_paise

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
                "bill_date":             data["bill_date"],
                "due_date":              data.get("due_date"),
                "is_interstate":         is_interstate,
                "taxable_amount_paise":  total_taxable,
                "cgst_paise":            total_cgst,
                "sgst_paise":            total_sgst,
                "igst_paise":            total_igst,
                "total_paise":           total_paise,
                "tds_paise":             tds_paise,
                "tds_section":           vendor.get("tds_section"),
                "net_payable_paise":     net_payable_paise,
                "status":                "draft",
                "notes":                 data.get("notes", ""),
                "created_at":            datetime.now(timezone.utc).isoformat(),
                "lines":                 computed_lines,
            }
            MOCK_PURCHASE_BILLS.append(bill)
            for ln in computed_lines:
                ln["id"]      = str(uuid.uuid4())
                ln["bill_id"] = bill_id
                MOCK_PURCHASE_BILL_LINES.append(ln)
            return api_response(True, bill)

        bill_payload = {
            "firm_id":               firm_id,
            "client_id":             client_id,
            "vendor_id":             vendor_id,
            "bill_no":               data.get("bill_no", ""),
            "bill_date":             data["bill_date"],
            "due_date":              data.get("due_date"),
            "is_interstate":         is_interstate,
            "taxable_amount_paise":  total_taxable,
            "cgst_paise":            total_cgst,
            "sgst_paise":            total_sgst,
            "igst_paise":            total_igst,
            "total_paise":           total_paise,
            "tds_paise":             tds_paise,
            "tds_section":           vendor.get("tds_section"),
            "net_payable_paise":     net_payable_paise,
            "status":                "draft",
            "notes":                 data.get("notes", ""),
            "created_at":            datetime.now(timezone.utc).isoformat(),
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
                "rate_paise":            ln["rate_paise"],
                "gst_rate_bps":          ln["gst_rate_bps"],
                "taxable_amount_paise":  ln["taxable_amount_paise"],
                "cgst_paise":            ln["cgst_paise"],
                "sgst_paise":            ln["sgst_paise"],
                "igst_paise":            ln["igst_paise"],
                "line_total_paise":      ln["line_total_paise"],
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
        return api_response(True, bill)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_purchase_bill: %s", e)
        return api_response(False, None, "Unable to create purchase bill. Please try again.")


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


@router.patch("/{bill_id}")
def update_purchase_bill(
    bill_id: str,
    data: PurchaseBillUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Update a draft purchase bill. Only allowed on draft status."""
    try:
        data = data.model_dump(exclude_none=True)
        if _USE_MOCK:
            for i, b in enumerate(MOCK_PURCHASE_BILLS):
                if b["id"] == bill_id:
                    if b.get("status") != "draft":
                        raise HTTPException(status_code=422, detail="Only draft bills can be updated")
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
        if resp.data[0]["status"] != "draft":
            raise HTTPException(status_code=422, detail="Only draft bills can be updated")
        # FY-lock: block editing a bill dated in a locked year, and block moving it
        # INTO a locked year. (Create already validates; edits were the gap.)
        firm_id = current_user.get("firm_id") or ""
        existing_date = resp.data[0].get("bill_date")
        if existing_date:
            period_validation_service.validate_posting_date(firm_id, existing_date)
        if data.get("bill_date"):
            period_validation_service.validate_posting_date(firm_id, data["bill_date"])

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
        db = get_supabase()
        # Tenant isolation (OOS-5): firm-scope the guard read and the write so a
        # foreign-firm bill id cannot be read or mutated under service-role.
        resp = db.table("purchase_bills").select("status").eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
        if resp.data[0]["status"] == "cancelled":
            raise HTTPException(status_code=422, detail="Bill already cancelled")

        upd = db.table("purchase_bills").update({
            "status":       "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).execute()
        updated = upd.data[0] if upd.data else {}
        log_event(
            current_user.get("firm_id", ""), "purchase_bill", bill_id,
            "status_change", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data={"status": "cancelled"},
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
                    "gst_rate_bps":         int(ln.get("gst_rate_bps", 0)),
                    "quantity":             ln.get("quantity", 1),
                    "taxable_amount_paise": int(ln.get("taxable_amount_paise", 0)),
                    "cgst_paise":           0,
                    "sgst_paise":           0,
                    "igst_paise":           0,
                    "line_total_paise":     int(ln.get("rate_paise", 0)),
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
