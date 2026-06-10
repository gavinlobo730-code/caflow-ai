"""Sales invoices — invoice creation with HSN/SAC, GST auto-computation, status tracking.
CGST Act Section 31: Tax invoice requirements.
CGST Act Section 8: Intra-state → CGST+SGST, Inter-state → IGST.
CGST Rule 46: Mandatory fields on tax invoice.
"""
import os
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from models.common import api_response
from core.permissions import rbac
from services.audit_service import log_event

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.sales_invoices")

router = APIRouter(prefix="/api/sales-invoices", tags=["sales_invoices"])

# ---------------------------------------------------------------------------
# Mock stores
# ---------------------------------------------------------------------------
MOCK_SALES_INVOICES: list[dict] = []
MOCK_SALES_INVOICE_LINES: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_fy() -> str:
    """Return financial year string like '2526' for FY 2025-26.
    Indian FY runs April 1 – March 31.
    """
    now = datetime.now(timezone.utc)
    if now.month >= 4:
        return f"{str(now.year)[2:]}{str(now.year + 1)[2:]}"
    return f"{str(now.year - 1)[2:]}{str(now.year)[2:]}"


def _next_invoice_seq(db, firm_id: str, client_id: str, fy: str) -> int:
    """Query the count of sales invoices for this firm+client in the current FY."""
    try:
        resp = (
            db.table("client_sales_invoices")
            .select("id", count="exact")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .like("invoice_no", f"SINV-{fy}-%")
            .execute()
        )
        return (resp.count or 0) + 1
    except Exception:
        return 1


def _compute_line_gst(
    taxable_paise: int,
    gst_rate_bps: int,
    is_interstate: bool,
) -> tuple[int, int, int]:
    """
    Compute CGST, SGST, IGST for a line in integer paise.
    CGST Act §8: Intra-state → CGST+SGST; Inter-state → IGST.
    All rates in basis points (bps). 1800 bps = 18%.
    Returns (cgst_paise, sgst_paise, igst_paise).
    """
    # Integer arithmetic — never floating point
    if is_interstate:
        igst_paise = (taxable_paise * gst_rate_bps) // 10000
        return 0, 0, igst_paise
    else:
        half_rate = gst_rate_bps // 2
        cgst_paise = (taxable_paise * half_rate) // 10000
        sgst_paise = (taxable_paise * half_rate) // 10000
        return cgst_paise, sgst_paise, 0


def _get_state_code_from_gstin(gstin: Optional[str]) -> Optional[str]:
    if gstin and len(gstin) >= 2:
        return gstin[:2]
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/outstanding")
def get_outstanding(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Sum of outstanding (unpaid) invoices for a client, in integer paise."""
    try:
        if _USE_MOCK:
            total = sum(
                (inv.get("total_paise", 0) - inv.get("paid_paise", 0))
                for inv in MOCK_SALES_INVOICES
                if inv["client_id"] == client_id and inv.get("status") not in ("paid", "cancelled")
            )
            return api_response(True, {"client_id": client_id, "outstanding_paise": total})

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = (
            db.table("client_sales_invoices")
            .select("total_paise,paid_paise")
            .eq("client_id", client_id)
            .not_.in_("status", ["paid", "cancelled"])
            .execute()
        )
        outstanding = sum(
            (r.get("total_paise", 0) - r.get("paid_paise", 0))
            for r in (resp.data or [])
        )
        return api_response(True, {"client_id": client_id, "outstanding_paise": outstanding})
    except Exception as e:
        _logger.error("get_outstanding: %s", e)
        return api_response(False, None, str(e))


@router.get("/")
def list_invoices(
    client_id: str = Query(..., description="CA client ID — required"),
    customer_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List sales invoices with optional filters."""
    try:
        if _USE_MOCK:
            result = [inv for inv in MOCK_SALES_INVOICES if inv["client_id"] == client_id]
            if customer_id:
                result = [inv for inv in result if inv.get("customer_id") == customer_id]
            if status:
                result = [inv for inv in result if inv.get("status") == status]
            # Attach lines
            for inv in result:
                inv["lines"] = [
                    ln for ln in MOCK_SALES_INVOICE_LINES if ln["invoice_id"] == inv["id"]
                ]
            return api_response(True, result)

        from core.supabase_client import get_supabase
        db = get_supabase()
        q = db.table("client_sales_invoices").select("*").eq("client_id", client_id)
        if customer_id:
            q = q.eq("customer_id", customer_id)
        if status:
            q = q.eq("status", status)
        if date_from:
            q = q.gte("invoice_date", date_from)
        if date_to:
            q = q.lte("invoice_date", date_to)
        resp = q.order("invoice_date", desc=True).execute()
        invoices = resp.data or []

        # Attach lines to each invoice
        for inv in invoices:
            lines_resp = (
                db.table("client_sales_invoice_lines")
                .select("*")
                .eq("invoice_id", inv["id"])
                .execute()
            )
            inv["lines"] = lines_resp.data or []

        return api_response(True, invoices)
    except Exception as e:
        _logger.error("list_invoices: %s", e)
        return api_response(False, None, str(e))


@router.post("/")
def create_invoice(
    data: dict,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Create a sales invoice with GST auto-computation.
    CGST Act §31: Tax invoice. CGST §8: CGST+SGST (intra), IGST (inter).
    CGST Rule 46: Mandatory fields — invoice_no, date, GSTIN, HSN, tax amounts.
    All monetary values in integer paise.
    """
    try:
        required = ["client_id", "customer_id", "invoice_date", "lines"]
        for field in required:
            if not data.get(field):
                raise HTTPException(status_code=422, detail=f"{field} is required")

        lines_data = data.get("lines", [])
        if not lines_data:
            raise HTTPException(status_code=422, detail="At least one line item is required")

        firm_id   = current_user.get("firm_id")
        client_id = data["client_id"]
        supply_state_code = data.get("supply_state_code", "")

        if _USE_MOCK:
            # Determine is_interstate from supply_state_code vs a placeholder "27" (Mumbai)
            is_interstate = False
            client_state_code = "27"
        else:
            from core.supabase_client import get_supabase
            db = get_supabase()

            # Fetch customer state code
            cust_resp = (
                db.table("customers")
                .select("state_code, gstin")
                .eq("id", data["customer_id"])
                .limit(1)
                .execute()
            )
            customer = cust_resp.data[0] if cust_resp.data else {}

            # Fetch client state code from GSTIN
            client_resp = (
                db.table("clients")
                .select("gstin")
                .eq("id", client_id)
                .limit(1)
                .execute()
            )
            client_rec = client_resp.data[0] if client_resp.data else {}
            client_state_code = _get_state_code_from_gstin(client_rec.get("gstin")) or ""

        # Effective place of supply
        effective_supply_state = supply_state_code or customer.get("state_code") or ""  # type: ignore[possibly-undefined]

        # CGST Act §8: Intra-state if both in same state; inter-state otherwise
        is_interstate = bool(client_state_code and effective_supply_state and client_state_code != effective_supply_state)

        # Compute lines — use Decimal for quantity × rate_paise, cast to int immediately
        computed_lines: list[dict] = []
        total_taxable_paise = 0
        total_cgst_paise    = 0
        total_sgst_paise    = 0
        total_igst_paise    = 0

        for ln in lines_data:
            qty        = ln.get("quantity", 1)
            rate_paise = int(ln.get("rate_paise", 0))
            gst_rate_bps = int(ln.get("gst_rate_bps", 0))

            # Integer multiplication: use Decimal for quantity precision, cast immediately
            taxable_paise = int(Decimal(str(qty)) * rate_paise)

            cgst_paise, sgst_paise, igst_paise = _compute_line_gst(
                taxable_paise, gst_rate_bps, is_interstate
            )

            total_taxable_paise += taxable_paise
            total_cgst_paise    += cgst_paise
            total_sgst_paise    += sgst_paise
            total_igst_paise    += igst_paise

            computed_lines.append({
                "description":    ln.get("description", ""),
                "hsn_sac":        ln.get("hsn_sac", ""),
                "quantity":       qty,
                "unit":           ln.get("unit", "NOS"),
                "rate_paise":     rate_paise,
                "gst_rate_bps":   gst_rate_bps,
                "taxable_amount_paise": taxable_paise,
                "cgst_paise":     cgst_paise,
                "sgst_paise":     sgst_paise,
                "igst_paise":     igst_paise,
                "line_total_paise": taxable_paise + cgst_paise + sgst_paise + igst_paise,
            })

        total_paise = total_taxable_paise + total_cgst_paise + total_sgst_paise + total_igst_paise

        if _USE_MOCK:
            fy = _current_fy()
            seq = len([i for i in MOCK_SALES_INVOICES if i["client_id"] == client_id]) + 1
            invoice_no = f"SINV-{fy}-{seq:04d}"
            invoice_id = str(uuid.uuid4())
            invoice = {
                "id":                    invoice_id,
                "firm_id":               firm_id,
                "client_id":             client_id,
                "customer_id":           data["customer_id"],
                "invoice_no":            invoice_no,
                "invoice_date":          data["invoice_date"],
                "due_date":              data.get("due_date"),
                "supply_state_code":     effective_supply_state,
                "is_interstate":         is_interstate,
                "taxable_amount_paise":  total_taxable_paise,
                "cgst_paise":            total_cgst_paise,
                "sgst_paise":            total_sgst_paise,
                "igst_paise":            total_igst_paise,
                "total_paise":           total_paise,
                "paid_paise":            0,
                "status":                "draft",
                "notes":                 data.get("notes", ""),
                "created_at":            datetime.now(timezone.utc).isoformat(),
                "lines":                 computed_lines,
            }
            MOCK_SALES_INVOICES.append(invoice)
            for ln in computed_lines:
                ln["id"] = str(uuid.uuid4())
                ln["invoice_id"] = invoice_id
                MOCK_SALES_INVOICE_LINES.append(ln)
            return api_response(True, invoice)

        # Generate invoice number
        fy = _current_fy()
        seq = _next_invoice_seq(db, firm_id, client_id, fy)  # type: ignore[possibly-undefined]
        invoice_no = f"SINV-{fy}-{seq:04d}"

        invoice_payload = {
            "firm_id":               firm_id,
            "client_id":             client_id,
            "customer_id":           data["customer_id"],
            "invoice_no":            invoice_no,
            "invoice_date":          data["invoice_date"],
            "due_date":              data.get("due_date"),
            "supply_state_code":     effective_supply_state,
            "is_interstate":         is_interstate,
            "taxable_amount_paise":  total_taxable_paise,
            "cgst_paise":            total_cgst_paise,
            "sgst_paise":            total_sgst_paise,
            "igst_paise":            total_igst_paise,
            "total_paise":           total_paise,
            "paid_paise":            0,
            "status":                "draft",
            "notes":                 data.get("notes", ""),
            "created_at":            datetime.now(timezone.utc).isoformat(),
        }

        inv_resp = db.table("client_sales_invoices").insert(invoice_payload).execute()  # type: ignore[possibly-undefined]
        invoice = inv_resp.data[0] if inv_resp.data else invoice_payload
        invoice_id = invoice.get("id", str(uuid.uuid4()))

        # Insert lines
        line_payloads = []
        for ln in computed_lines:
            line_payloads.append({
                "invoice_id":            invoice_id,
                "description":           ln["description"],
                "hsn_sac":               ln["hsn_sac"],
                "quantity":              ln["quantity"],
                "unit":                  ln["unit"],
                "rate_paise":            ln["rate_paise"],
                "gst_rate_bps":          ln["gst_rate_bps"],
                "taxable_amount_paise":  ln["taxable_amount_paise"],
                "cgst_paise":            ln["cgst_paise"],
                "sgst_paise":            ln["sgst_paise"],
                "igst_paise":            ln["igst_paise"],
                "line_total_paise":      ln["line_total_paise"],
            })
        lines_resp = db.table("client_sales_invoice_lines").insert(line_payloads).execute()  # type: ignore[possibly-undefined]
        invoice["lines"] = lines_resp.data or computed_lines

        log_event(
            firm_id, "sales_invoice", invoice_id,
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=invoice,
        )
        return api_response(True, invoice)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_invoice: %s", e)
        return api_response(False, None, str(e))


@router.get("/{invoice_id}")
def get_invoice(
    invoice_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Get a single invoice with its line items."""
    try:
        if _USE_MOCK:
            inv = next((i for i in MOCK_SALES_INVOICES if i["id"] == invoice_id), None)
            if not inv:
                raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
            inv["lines"] = [ln for ln in MOCK_SALES_INVOICE_LINES if ln["invoice_id"] == invoice_id]
            return api_response(True, inv)

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("client_sales_invoices").select("*").eq("id", invoice_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        invoice = resp.data[0]
        lines_resp = db.table("client_sales_invoice_lines").select("*").eq("invoice_id", invoice_id).execute()
        invoice["lines"] = lines_resp.data or []
        return api_response(True, invoice)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_invoice: %s", e)
        return api_response(False, None, str(e))


@router.patch("/{invoice_id}")
def update_invoice(
    invoice_id: str,
    data: dict,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Update a draft invoice. Recomputes GST if lines are changed. Only allowed on draft status."""
    try:
        if _USE_MOCK:
            for i, inv in enumerate(MOCK_SALES_INVOICES):
                if inv["id"] == invoice_id:
                    if inv.get("status") != "draft":
                        raise HTTPException(status_code=422, detail="Only draft invoices can be updated")
                    MOCK_SALES_INVOICES[i] = {**inv, **data, "updated_at": datetime.now(timezone.utc).isoformat()}
                    return api_response(True, MOCK_SALES_INVOICES[i])
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()

        # Check current status
        resp = db.table("client_sales_invoices").select("status").eq("id", invoice_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        if resp.data[0]["status"] != "draft":
            raise HTTPException(status_code=422, detail="Only draft invoices can be updated")

        # If lines are provided, recompute GST
        if "lines" in data:
            # Fetch current invoice for is_interstate flag
            inv_resp = db.table("client_sales_invoices").select("*").eq("id", invoice_id).limit(1).execute()
            inv = inv_resp.data[0]
            is_interstate = inv.get("is_interstate", False)

            computed_lines = []
            total_taxable = 0
            total_cgst    = 0
            total_sgst    = 0
            total_igst    = 0

            for ln in data["lines"]:
                qty          = ln.get("quantity", 1)
                rate_paise   = int(ln.get("rate_paise", 0))
                gst_rate_bps = int(ln.get("gst_rate_bps", 0))
                taxable      = int(Decimal(str(qty)) * rate_paise)
                cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, is_interstate)

                total_taxable += taxable
                total_cgst    += cgst
                total_sgst    += sgst
                total_igst    += igst

                computed_lines.append({
                    "invoice_id":           invoice_id,
                    "description":          ln.get("description", ""),
                    "hsn_sac":              ln.get("hsn_sac", ""),
                    "quantity":             qty,
                    "unit":                 ln.get("unit", "NOS"),
                    "rate_paise":           rate_paise,
                    "gst_rate_bps":         gst_rate_bps,
                    "taxable_amount_paise": taxable,
                    "cgst_paise":           cgst,
                    "sgst_paise":           sgst,
                    "igst_paise":           igst,
                    "line_total_paise":     taxable + cgst + sgst + igst,
                })

            # Delete existing lines and reinsert
            db.table("client_sales_invoice_lines").delete().eq("invoice_id", invoice_id).execute()
            db.table("client_sales_invoice_lines").insert(computed_lines).execute()

            # Update aggregate totals in invoice
            data.pop("lines")
            data["taxable_amount_paise"] = total_taxable
            data["cgst_paise"]           = total_cgst
            data["sgst_paise"]           = total_sgst
            data["igst_paise"]           = total_igst
            data["total_paise"]          = total_taxable + total_cgst + total_sgst + total_igst

        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        upd_resp = db.table("client_sales_invoices").update(data).eq("id", invoice_id).execute()
        updated = upd_resp.data[0] if upd_resp.data else data
        log_event(
            current_user.get("firm_id", ""), "sales_invoice", invoice_id,
            "update", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=updated,
        )
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_invoice: %s", e)
        return api_response(False, None, str(e))


@router.post("/{invoice_id}/issue")
def issue_invoice(
    invoice_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Transition invoice from draft → issued.
    Auto-creates a posted journal entry via Phase2JournalService.
    CGST Act §31: Invoice must be issued before GST reporting.
    """
    try:
        from services.phase2_journal_service import phase2_journal_service

        if _USE_MOCK:
            for i, inv in enumerate(MOCK_SALES_INVOICES):
                if inv["id"] == invoice_id:
                    if inv.get("status") != "draft":
                        raise HTTPException(status_code=422, detail="Only draft invoices can be issued")
                    MOCK_SALES_INVOICES[i]["status"] = "issued"
                    MOCK_SALES_INVOICES[i]["issued_at"] = datetime.now(timezone.utc).isoformat()
                    phase2_journal_service.journal_for_sales_invoice(
                        MOCK_SALES_INVOICES[i],
                        current_user.get("firm_id", ""),
                        MOCK_SALES_INVOICES[i]["client_id"],
                    )
                    return api_response(True, MOCK_SALES_INVOICES[i])
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("client_sales_invoices").select("*").eq("id", invoice_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        inv = resp.data[0]
        if inv.get("status") != "draft":
            raise HTTPException(status_code=422, detail="Only draft invoices can be issued")

        now_iso = datetime.now(timezone.utc).isoformat()
        upd = db.table("client_sales_invoices").update({
            "status":    "issued",
            "issued_at": now_iso,
        }).eq("id", invoice_id).execute()
        updated_inv = upd.data[0] if upd.data else {**inv, "status": "issued"}

        # Auto-create journal entry — CGST Act §9
        journal_id = phase2_journal_service.journal_for_sales_invoice(
            invoice=updated_inv,
            firm_id=current_user.get("firm_id", ""),
            client_id=updated_inv.get("client_id", ""),
        )

        log_event(
            current_user.get("firm_id", ""), "sales_invoice", invoice_id,
            "status_change", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"status": "issued", "journal_entry_id": journal_id},
        )
        updated_inv["journal_entry_id"] = journal_id
        return api_response(True, updated_inv)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("issue_invoice: %s", e)
        return api_response(False, None, str(e))


@router.post("/{invoice_id}/cancel")
def cancel_invoice(
    invoice_id: str,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Cancel a sales invoice. Requires accounting.approve (Partner only)."""
    try:
        if _USE_MOCK:
            for i, inv in enumerate(MOCK_SALES_INVOICES):
                if inv["id"] == invoice_id:
                    if inv.get("status") == "cancelled":
                        raise HTTPException(status_code=422, detail="Invoice already cancelled")
                    MOCK_SALES_INVOICES[i]["status"] = "cancelled"
                    MOCK_SALES_INVOICES[i]["cancelled_at"] = datetime.now(timezone.utc).isoformat()
                    return api_response(True, MOCK_SALES_INVOICES[i])
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("client_sales_invoices").select("status").eq("id", invoice_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        if resp.data[0]["status"] == "cancelled":
            raise HTTPException(status_code=422, detail="Invoice already cancelled")

        upd = db.table("client_sales_invoices").update({
            "status":       "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", invoice_id).execute()

        updated = upd.data[0] if upd.data else {}
        log_event(
            current_user.get("firm_id", ""), "sales_invoice", invoice_id,
            "status_change", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data={"status": "cancelled"},
        )
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("cancel_invoice: %s", e)
        return api_response(False, None, str(e))
