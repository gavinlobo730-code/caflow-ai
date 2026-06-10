"""Credit notes — sales returns with GST reversal.
CGST Act Section 34: Credit notes for reduction in taxable value or tax charged.
CGST Act Section 8: Intra-state → CGST+SGST; Inter-state → IGST.
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
_logger = logging.getLogger("caflow.credit_notes")

router = APIRouter(prefix="/api/credit-notes", tags=["credit_notes"])

# ---------------------------------------------------------------------------
# Mock stores
# ---------------------------------------------------------------------------
MOCK_CREDIT_NOTES: list[dict] = []
MOCK_CREDIT_NOTE_LINES: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _current_fy() -> str:
    now = datetime.now(timezone.utc)
    if now.month >= 4:
        return f"{str(now.year)[2:]}{str(now.year + 1)[2:]}"
    return f"{str(now.year - 1)[2:]}{str(now.year)[2:]}"


def _next_cn_seq(db, firm_id: str, client_id: str, fy: str) -> int:
    try:
        resp = (
            db.table("credit_notes")
            .select("id", count="exact")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .like("credit_note_no", f"CN-{fy}-%")
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


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_credit_notes(
    client_id: str = Query(..., description="CA client ID — required"),
    customer_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List credit notes for a client."""
    try:
        if _USE_MOCK:
            result = [cn for cn in MOCK_CREDIT_NOTES if cn["client_id"] == client_id]
            if customer_id:
                result = [cn for cn in result if cn.get("customer_id") == customer_id]
            return api_response(True, result)

        from core.supabase_client import get_supabase
        db = get_supabase()
        q = db.table("credit_notes").select("*").eq("client_id", client_id)
        if customer_id:
            q = q.eq("customer_id", customer_id)
        resp = q.order("credit_note_date", desc=True).execute()
        return api_response(True, resp.data or [])
    except Exception as e:
        _logger.error("list_credit_notes: %s", e)
        return api_response(False, None, str(e))


@router.post("/")
def create_credit_note(
    data: dict,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Create a credit note.
    If sales_invoice_id is provided, inherit is_interstate from that invoice.
    CGST Act §34: Credit notes must reference the original supply.
    All money in integer paise.
    """
    try:
        required = ["client_id", "customer_id", "credit_note_date", "lines"]
        for field in required:
            if not data.get(field):
                raise HTTPException(status_code=422, detail=f"{field} is required")

        firm_id   = current_user.get("firm_id")
        client_id = data["client_id"]
        lines_data = data.get("lines", [])
        if not lines_data:
            raise HTTPException(status_code=422, detail="At least one line item is required")

        # Determine is_interstate
        is_interstate = False
        original_invoice = None

        if _USE_MOCK:
            # Mock: if sales_invoice_id given, look it up
            if data.get("sales_invoice_id"):
                try:
                    from routers.sales_invoices import MOCK_SALES_INVOICES  # mock store, table is client_sales_invoices in DB
                    original_invoice = next(
                        (i for i in MOCK_SALES_INVOICES if i["id"] == data["sales_invoice_id"]),
                        None
                    )
                    if original_invoice:
                        is_interstate = original_invoice.get("is_interstate", False)
                except ImportError:
                    pass
        else:
            from core.supabase_client import get_supabase
            db = get_supabase()
            if data.get("sales_invoice_id"):
                inv_resp = (
                    db.table("client_sales_invoices")
                    .select("is_interstate")
                    .eq("id", data["sales_invoice_id"])
                    .limit(1)
                    .execute()
                )
                if inv_resp.data:
                    is_interstate = inv_resp.data[0].get("is_interstate", False)

        # Compute lines
        computed_lines: list[dict] = []
        total_taxable = 0
        total_cgst    = 0
        total_sgst    = 0
        total_igst    = 0

        for ln in lines_data:
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
                "description":          ln.get("description", ""),
                "hsn_sac":              ln.get("hsn_sac", ""),
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
        fy = _current_fy()

        if _USE_MOCK:
            seq = len([cn for cn in MOCK_CREDIT_NOTES if cn["client_id"] == client_id]) + 1
            cn_no = f"CN-{fy}-{seq:04d}"
            cn_id = str(uuid.uuid4())
            cn = {
                "id":                   cn_id,
                "firm_id":              firm_id,
                "client_id":            client_id,
                "customer_id":          data["customer_id"],
                "sales_invoice_id":     data.get("sales_invoice_id"),
                "credit_note_no":       cn_no,
                "credit_note_date":     data["credit_note_date"],
                "reason":               data.get("reason", ""),
                "is_interstate":        is_interstate,
                "taxable_amount_paise": total_taxable,
                "cgst_paise":           total_cgst,
                "sgst_paise":           total_sgst,
                "igst_paise":           total_igst,
                "total_paise":          total_paise,
                "status":               "draft",
                "created_at":           datetime.now(timezone.utc).isoformat(),
                "lines":                computed_lines,
            }
            MOCK_CREDIT_NOTES.append(cn)
            for ln in computed_lines:
                ln["id"]             = str(uuid.uuid4())
                ln["credit_note_id"] = cn_id
                MOCK_CREDIT_NOTE_LINES.append(ln)
            return api_response(True, cn)

        seq   = _next_cn_seq(db, firm_id, client_id, fy)  # type: ignore[possibly-undefined]
        cn_no = f"CN-{fy}-{seq:04d}"

        cn_payload = {
            "firm_id":              firm_id,
            "client_id":            client_id,
            "customer_id":          data["customer_id"],
            "sales_invoice_id":     data.get("sales_invoice_id"),
            "credit_note_no":       cn_no,
            "credit_note_date":     data["credit_note_date"],
            "reason":               data.get("reason", ""),
            "is_interstate":        is_interstate,
            "taxable_amount_paise": total_taxable,
            "cgst_paise":           total_cgst,
            "sgst_paise":           total_sgst,
            "igst_paise":           total_igst,
            "total_paise":          total_paise,
            "status":               "draft",
            "created_at":           datetime.now(timezone.utc).isoformat(),
        }

        cn_resp = db.table("credit_notes").insert(cn_payload).execute()  # type: ignore[possibly-undefined]
        cn      = cn_resp.data[0] if cn_resp.data else cn_payload
        cn_id   = cn.get("id", str(uuid.uuid4()))

        line_payloads = [
            {
                "credit_note_id":       cn_id,
                "description":          ln["description"],
                "hsn_sac":              ln["hsn_sac"],
                "quantity":             ln["quantity"],
                "rate_paise":           ln["rate_paise"],
                "gst_rate_bps":         ln["gst_rate_bps"],
                "taxable_amount_paise": ln["taxable_amount_paise"],
                "cgst_paise":           ln["cgst_paise"],
                "sgst_paise":           ln["sgst_paise"],
                "igst_paise":           ln["igst_paise"],
                "line_total_paise":     ln["line_total_paise"],
            }
            for ln in computed_lines
        ]
        lines_resp = db.table("credit_note_lines").insert(line_payloads).execute()  # type: ignore[possibly-undefined]
        cn["lines"] = lines_resp.data or computed_lines

        log_event(
            firm_id or "", "credit_note", cn_id,
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=cn,
        )
        return api_response(True, cn)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_credit_note: %s", e)
        return api_response(False, None, str(e))


@router.get("/{cn_id}")
def get_credit_note(
    cn_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Get a single credit note with its line items."""
    try:
        if _USE_MOCK:
            cn = next((c for c in MOCK_CREDIT_NOTES if c["id"] == cn_id), None)
            if not cn:
                raise HTTPException(status_code=404, detail=f"Credit note {cn_id} not found")
            cn["lines"] = [ln for ln in MOCK_CREDIT_NOTE_LINES if ln.get("credit_note_id") == cn_id]
            return api_response(True, cn)

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("credit_notes").select("*").eq("id", cn_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Credit note {cn_id} not found")
        cn = resp.data[0]
        lines_resp = db.table("credit_note_lines").select("*").eq("credit_note_id", cn_id).execute()
        cn["lines"] = lines_resp.data or []
        return api_response(True, cn)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_credit_note: %s", e)
        return api_response(False, None, str(e))


@router.post("/{cn_id}/issue")
def issue_credit_note(
    cn_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Transition credit note draft → issued.
    Auto-creates journal entry via Phase2JournalService.
    CGST Act §34: Credit note must be issued to reverse GST liability.
    """
    try:
        from services.phase2_journal_service import phase2_journal_service

        if _USE_MOCK:
            for i, cn in enumerate(MOCK_CREDIT_NOTES):
                if cn["id"] == cn_id:
                    if cn.get("status") != "draft":
                        raise HTTPException(status_code=422, detail="Only draft credit notes can be issued")
                    MOCK_CREDIT_NOTES[i]["status"]    = "issued"
                    MOCK_CREDIT_NOTES[i]["issued_at"] = datetime.now(timezone.utc).isoformat()
                    phase2_journal_service.journal_for_credit_note(
                        MOCK_CREDIT_NOTES[i],
                        current_user.get("firm_id", ""),
                        MOCK_CREDIT_NOTES[i]["client_id"],
                    )
                    return api_response(True, MOCK_CREDIT_NOTES[i])
            raise HTTPException(status_code=404, detail=f"Credit note {cn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("credit_notes").select("*").eq("id", cn_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Credit note {cn_id} not found")
        cn = resp.data[0]
        if cn.get("status") != "draft":
            raise HTTPException(status_code=422, detail="Only draft credit notes can be issued")

        now_iso = datetime.now(timezone.utc).isoformat()
        upd = db.table("credit_notes").update({
            "status":    "issued",
            "issued_at": now_iso,
        }).eq("id", cn_id).execute()
        updated_cn = upd.data[0] if upd.data else {**cn, "status": "issued"}

        journal_id = phase2_journal_service.journal_for_credit_note(
            cn=updated_cn,
            firm_id=current_user.get("firm_id", ""),
            client_id=updated_cn.get("client_id", ""),
        )

        log_event(
            current_user.get("firm_id", ""), "credit_note", cn_id,
            "status_change", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"status": "issued", "journal_entry_id": journal_id},
        )
        updated_cn["journal_entry_id"] = journal_id
        return api_response(True, updated_cn)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("issue_credit_note: %s", e)
        return api_response(False, None, str(e))
