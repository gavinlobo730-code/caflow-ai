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
from pydantic import BaseModel, field_validator
from models.common import api_response
from models.invoices import InvoiceLineIn
from core.permissions import rbac
from services.audit_service import log_event
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service


class CreditNoteIn(BaseModel):
    client_id: str
    customer_id: str
    credit_note_date: str  # YYYY-MM-DD
    lines: list[InvoiceLineIn]
    sales_invoice_id: str | None = None
    reference_no: str | None = None
    notes: str | None = None
    is_interstate: bool = False

    @field_validator("lines")
    @classmethod
    def at_least_one_line(cls, v: list) -> list:
        if not v:
            raise ValueError("Credit note must have at least one line.")
        return v

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.credit_notes")


def _current_fy_long() -> str:
    """Return full financial year string like '2025-26' for display/timeline use.
    Indian FY runs April 1 – March 31.
    """
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"

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
            result = [cn for cn in MOCK_CREDIT_NOTES if cn["client_id"] == client_id and not cn.get("deleted_at")]
            if customer_id:
                result = [cn for cn in result if cn.get("customer_id") == customer_id]
            return api_response(True, result)

        from core.supabase_client import get_supabase
        db = get_supabase()
        # Tenant isolation: the service-role client bypasses RLS, so the firm filter
        # is the ONLY thing preventing a cross-tenant read via a guessed client_id (H15/L4).
        q = (db.table("credit_notes").select("*")
             .eq("firm_id", current_user.get("firm_id")).eq("client_id", client_id).is_("deleted_at", None))
        if customer_id:
            q = q.eq("customer_id", customer_id)
        resp = q.order("credit_note_date", desc=True).execute()
        return api_response(True, resp.data or [])
    except Exception as e:
        _logger.error("list_credit_notes: %s", e)
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")


@router.post("/")
def create_credit_note(
    data: CreditNoteIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Create a credit note.
    If sales_invoice_id is provided, inherit is_interstate from that invoice.
    CGST Act §34: Credit notes must reference the original supply.
    All money in integer paise.
    """
    try:
        data = data.model_dump()
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
            # Line rate arrives as gst_rate_percent on the shared InvoiceLineIn model;
            # fall back to an explicit gst_rate_bps if a caller supplies one. (Reading
            # only gst_rate_bps previously yielded 0% GST on standalone credit notes.)
            gst_rate_bps = int(ln.get("gst_rate_bps") or 0)
            if not gst_rate_bps and ln.get("gst_rate_percent"):
                gst_rate_bps = int(round(float(ln.get("gst_rate_percent")) * 100))
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
                # Which Product/Service (goods only, in practice) this return
                # restocks — migration 189. Optional: a line with no pick just
                # never moves stock (domain.inventory_service.apply_credit_note_to_inventory).
                "service_catalogue_id": ln.get("service_catalogue_id"),
            })

        total_paise = total_taxable + total_cgst + total_sgst + total_igst

        # Validate posting date is not in a locked financial year (migration 020)
        period_validation_service.validate_posting_date(firm_id or "", data["credit_note_date"])

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
                "total_gst_paise":      total_cgst + total_sgst + total_igst,
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

        cn_payload = {
            "firm_id":              firm_id,
            "client_id":            client_id,
            "customer_id":          data["customer_id"],
            "sales_invoice_id":     data.get("sales_invoice_id"),
            "credit_note_date":     data["credit_note_date"],
            "reason":               data.get("reason", ""),
            "is_interstate":        is_interstate,
            "taxable_amount_paise": total_taxable,
            "cgst_paise":           total_cgst,
            "sgst_paise":           total_sgst,
            "igst_paise":           total_igst,
            "total_paise":          total_paise,
            "total_gst_paise":      total_cgst + total_sgst + total_igst,
            "status":               "draft",
            "created_at":           datetime.now(timezone.utc).isoformat(),
        }

        from services.numbering import insert_numbered_document_with_lines
        cn = insert_numbered_document_with_lines(
            db, "credit_notes", cn_payload, "credit_note_no",
            lambda s: f"CN-{fy}-{s:04d}",
            lambda: _next_cn_seq(db, firm_id, client_id, fy),
            "credit_note_lines", computed_lines, "credit_note_id")
        cn_id = cn.get("id", str(uuid.uuid4()))
        cn["lines"] = computed_lines

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
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")


@router.get("/{cn_id}")
def get_credit_note(
    cn_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Get a single credit note with its line items."""
    try:
        if _USE_MOCK:
            cn = next((c for c in MOCK_CREDIT_NOTES if c["id"] == cn_id and not c.get("deleted_at")), None)
            if not cn:
                raise HTTPException(status_code=404, detail=f"Credit note {cn_id} not found")
            cn["lines"] = [ln for ln in MOCK_CREDIT_NOTE_LINES if ln.get("credit_note_id") == cn_id]
            return api_response(True, cn)

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = (db.table("credit_notes").select("*").eq("id", cn_id)
                .eq("firm_id", current_user.get("firm_id")).is_("deleted_at", None).limit(1).execute())
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
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")


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
        firm_id = current_user.get("firm_id")
        # Tenant isolation (OOS-5): firm-scope the guard read and the write so a
        # foreign-firm credit-note id cannot be read or mutated under service-role.
        resp = db.table("credit_notes").select("*").eq("id", cn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Credit note {cn_id} not found")
        cn = resp.data[0]
        if cn.get("status") != "draft":
            raise HTTPException(status_code=422, detail="Only draft credit notes can be issued")
        # FY-lock: issuing posts a dated journal — block if the year was locked after
        # the draft was created (deferred-posting gap).
        if cn.get("credit_note_date"):
            period_validation_service.validate_posting_date(firm_id or "", cn["credit_note_date"])

        client_id = cn.get("client_id", "")
        cn_total  = int(cn.get("total_paise") or 0)
        inv_id    = cn.get("sales_invoice_id")

        # ── (C1) Apply the credit note to the linked invoice's SUB-LEDGER before
        # posting to the GL, capturing prior values for rollback. A credit note may
        # not exceed the invoice's net outstanding (CGST Act §34: it corrects an
        # existing supply's value/tax and cannot exceed it). This keeps the invoice
        # sub-ledger, the GL AR control (moved by the journal below) and the customer
        # statement reconciled: invoice net outstanding = total − paid − credited.
        prior_inv = None
        if inv_id and cn_total > 0:
            inv_resp = (db.table("client_sales_invoices")
                        .select("total_paise,paid_paise,credited_paise,status")
                        .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute())
            if not inv_resp.data:
                raise HTTPException(status_code=422, detail="Linked invoice is not part of this client's books.")
            inv = inv_resp.data[0]
            if (inv.get("status") or "") in ("draft", "cancelled"):
                raise HTTPException(status_code=422, detail=f"Cannot credit a {inv.get('status')} invoice.")
            total    = int(inv.get("total_paise") or 0)
            paid     = int(inv.get("paid_paise") or 0)
            credited = int(inv.get("credited_paise") or 0)
            net_outstanding = total - paid - credited
            if cn_total > net_outstanding:
                raise HTTPException(
                    status_code=422,
                    detail=(f"Credit note (₹{cn_total / 100:,.2f}) exceeds the invoice's outstanding "
                            f"(₹{net_outstanding / 100:,.2f})."),
                )
            prior_inv = {"credited_paise": credited, "status": inv.get("status")}
            new_credited = credited + cn_total
            settled = paid + new_credited
            new_status = "paid" if settled >= total else ("partially_paid" if settled > 0 else inv.get("status"))
            db.table("client_sales_invoices").update({
                "credited_paise": new_credited, "status": new_status,
            }).eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
            try:
                db.table("credit_note_allocations").insert({
                    "firm_id": firm_id, "credit_note_id": cn_id,
                    "sales_invoice_id": inv_id, "allocated_paise": cn_total,
                }).execute()
            except Exception:
                db.table("client_sales_invoices").update({
                    "credited_paise": credited, "status": prior_inv["status"],
                }).eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
                raise

        # ── Post the GL journal (Dr Sales Returns + Dr GST reversed / Cr Trade
        # Receivables). On failure, roll back the sub-ledger application so the books
        # never go partial; the credit note stays a re-tryable draft.
        try:
            journal_id = phase2_journal_service.journal_for_credit_note(
                cn=cn, firm_id=firm_id or "", client_id=client_id,
            )
            if not journal_id:
                raise RuntimeError("credit-note journal posting returned no id")
        except Exception as jerr:
            if prior_inv is not None and inv_id:
                try:
                    db.table("credit_note_allocations").delete().eq("credit_note_id", cn_id).eq("sales_invoice_id", inv_id).execute()
                    db.table("client_sales_invoices").update({
                        "credited_paise": prior_inv["credited_paise"], "status": prior_inv["status"],
                    }).eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
                except Exception:
                    pass
            _logger.error("issue_credit_note: journal posting failed; application rolled back: %s", jerr)
            return api_response(False, None, "Unable to issue credit note. Please try again.")

        # ── Mark the credit note issued and record how much was applied to invoices.
        now_iso = datetime.now(timezone.utc).isoformat()
        applied = cn_total if (inv_id and cn_total > 0) else 0
        upd = db.table("credit_notes").update({
            "status": "issued", "issued_at": now_iso, "applied_paise": applied,
        }).eq("id", cn_id).eq("firm_id", firm_id).execute()
        updated_cn = upd.data[0] if upd.data else {**cn, "status": "issued", "applied_paise": applied}

        log_event(
            firm_id or "", "credit_note", cn_id,
            "status_change", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"status": "issued", "journal_entry_id": journal_id, "applied_paise": applied},
        )
        # Record timeline event for issued credit note
        timeline_service.log_timeline_event(
            client_id=client_id,
            firm_id=firm_id or "",
            financial_year=_current_fy_long(),
            category="accounting",
            event_type="credit_note_issued",
            title=f"Credit Note {updated_cn.get('credit_note_no', '')} issued",
            description=f"Credit note for ₹{updated_cn.get('total_paise', 0) // 100:,} issued.",
            severity="success",
            entity_type="credit_note",
            entity_id=cn_id,
            amount_paise=updated_cn.get("total_paise"),
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )

        # Inventory: sales return — goods physically return to stock (goods
        # lines only). Runs AFTER issuance and the AR/GL effects above have
        # committed — never blocks issuing the credit note.
        try:
            from domain.inventory_service import apply_credit_note_to_inventory
            apply_credit_note_to_inventory(
                db, firm_id=firm_id or "", client_id=client_id,
                # journal_entries.created_by FK references users(id), not auth_user_id.
                credit_note=updated_cn, created_by=current_user.get("id"),
            )
        except Exception as e:
            _logger.error("issue_credit_note: inventory apply failed for %s: %s", cn_id, e, exc_info=True)

        updated_cn["journal_entry_id"] = journal_id
        return api_response(True, updated_cn)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("issue_credit_note: %s", e)
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")


# Human-readable phrasing for statuses that block deletion.
_DELETE_BLOCKED = {"issued": "an issued", "applied": "an applied"}


@router.delete("/{cn_id}")
def delete_credit_note(
    cn_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Soft-delete a DRAFT credit note.

    Only drafts may be deleted. Issued/applied credit notes are protected —
    once issued they carry a posted journal and, if linked to an invoice,
    have already reduced that invoice's outstanding balance (CGST Act §34);
    removing one outright would corrupt both. Deletion is a soft-delete
    (sets deleted_at, migration 183) plus an immutable audit_log 'delete'
    event, mirroring sales_invoices.delete_invoice exactly.
    """
    try:
        if _USE_MOCK:
            for i, cn in enumerate(MOCK_CREDIT_NOTES):
                if cn["id"] == cn_id and not cn.get("deleted_at"):
                    st = cn.get("status")
                    if st != "draft":
                        raise HTTPException(
                            status_code=422,
                            detail=f"Cannot delete {_DELETE_BLOCKED.get(st, st)} credit note — only drafts can be deleted",
                        )
                    MOCK_CREDIT_NOTES.pop(i)
                    return api_response(True, {"id": cn_id, "deleted": True})
            raise HTTPException(status_code=404, detail=f"Credit note {cn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = (
            db.table("credit_notes").select("*")
            .eq("id", cn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Credit note {cn_id} not found")
        cn = resp.data[0]
        st = cn.get("status")
        if st != "draft":
            raise HTTPException(
                status_code=422,
                detail=f"Cannot delete {_DELETE_BLOCKED.get(st, st)} credit note — only drafts can be deleted",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        db.table("credit_notes").update({"deleted_at": now_iso}).eq("id", cn_id).eq("firm_id", firm_id).execute()

        log_event(
            firm_id or "", "credit_note", cn_id,
            "delete", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            old_data={
                "credit_note_no": cn.get("credit_note_no"),
                "status":         st,
                "total_paise":    cn.get("total_paise"),
            },
        )
        return api_response(True, {"id": cn_id, "deleted": True})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_credit_note: %s", e)
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")
