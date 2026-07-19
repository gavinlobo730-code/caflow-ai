"""Sales debit notes — increase to a customer's payable (undercharge correction).

The sales-side mirror of credit_notes.py, for the OTHER direction CGST Act §34
covers: §34(3), where the value/tax charged on the original invoice was found
to be LESS than what should have been charged (undercharge, price escalation
after supply, additional charges). A debit note here DEBITS the customer's
receivable — increases what they owe — the exact inverse of a credit note.

A sales debit note increases the linked invoice's PAYABLE in the sub-ledger
(debit_note_paise + sales_debit_note_allocations) and posts a kernel journal
(Dr Trade Receivables / Cr Sales / Cr GST Output) so the AR sub-ledger, the GL
AR control and the customer statement stay reconciled:
  invoice net outstanding = (total_paise + debit_note_paise) - paid_paise - credited_paise.

Unlike a credit note, there is no "exceeds outstanding" ceiling on issue — you
can always owe more; the amount just adds to what's still due.

Scope (MVP Phase 1): modelled purely as a financial/GST correction — it does
NOT move inventory. The common real-world case for undercharging is a rate or
tax correction, not additional physical goods shipped; if a future need for
"additional units shipped, not on the original invoice" emerges, that's a
separate feature, not a natural extension of this one.

CGST Act Section 34: debit/credit notes for change in taxable value or tax.
CGST Act Section 8: Intra-state → CGST+SGST; Inter-state → IGST.
Integer paise throughout.
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


class SalesDebitNoteIn(BaseModel):
    client_id: str
    customer_id: str
    debit_note_date: str  # YYYY-MM-DD
    lines: list[InvoiceLineIn]
    sales_invoice_id: str | None = None
    reason: str | None = None
    is_interstate: bool = False

    @field_validator("lines")
    @classmethod
    def at_least_one_line(cls, v: list) -> list:
        if not v:
            raise ValueError("Debit note must have at least one line.")
        return v


class SalesDebitNoteUpdateIn(BaseModel):
    customer_id: str | None = None
    debit_note_date: str | None = None
    sales_invoice_id: str | None = None
    reason: str | None = None
    is_interstate: bool | None = None
    lines: list[InvoiceLineIn] | None = None
    notes: str | None = None


_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.sales_debit_notes")
router = APIRouter(prefix="/api/sales-debit-notes", tags=["sales_debit_notes"])

MOCK_SALES_DEBIT_NOTES: list[dict] = []
MOCK_SALES_DEBIT_NOTE_LINES: list[dict] = []


def _current_fy() -> str:
    now = datetime.now(timezone.utc)
    if now.month >= 4:
        return f"{str(now.year)[2:]}{str(now.year + 1)[2:]}"
    return f"{str(now.year - 1)[2:]}{str(now.year)[2:]}"


def _current_fy_long() -> str:
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def _next_sdn_seq(db, firm_id: str, client_id: str, fy: str) -> int:
    try:
        resp = (db.table("sales_debit_notes").select("id", count="exact")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .like("debit_note_no", f"SDN-{fy}-%").execute())
        return (resp.count or 0) + 1
    except Exception:
        return 1


def _compute_line_gst(taxable: int, gst_rate_bps: int, is_interstate: bool) -> tuple[int, int, int]:
    if is_interstate:
        return 0, 0, (taxable * gst_rate_bps) // 10000
    # Full tax first, then split (SGST carries any odd paise) — matches the
    # sales-side fix in routers/sales_invoices.py.
    full_gst = (taxable * gst_rate_bps) // 10000
    cgst = full_gst // 2
    return cgst, full_gst - cgst, 0


def _compute_lines(lines_data: list, is_interstate: bool):
    computed, total_taxable, total_cgst, total_sgst, total_igst = [], 0, 0, 0, 0
    for ln in lines_data:
        ln = ln if isinstance(ln, dict) else ln.model_dump()
        qty = ln.get("quantity", 1)
        rate_paise = int(ln.get("rate_paise", 0))
        gst_rate_bps = int(ln.get("gst_rate_bps") or 0)
        if not gst_rate_bps and ln.get("gst_rate_percent"):
            gst_rate_bps = int(round(float(ln.get("gst_rate_percent")) * 100))
        taxable = int(Decimal(str(qty)) * rate_paise)
        cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, is_interstate)
        total_taxable += taxable; total_cgst += cgst; total_sgst += sgst; total_igst += igst
        computed.append({
            "description": ln.get("description", ""), "hsn_sac": ln.get("hsn_sac", ""),
            "quantity": qty, "unit": ln.get("unit") or "NOS", "rate_paise": rate_paise, "gst_rate_bps": gst_rate_bps,
            "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst,
            "igst_paise": igst, "line_total_paise": taxable + cgst + sgst + igst,
            "service_catalogue_id": ln.get("service_catalogue_id"),
        })
    return computed, total_taxable, total_cgst, total_sgst, total_igst


@router.get("/")
def list_sales_debit_notes(
    client_id: str = Query(..., description="CA client ID — required"),
    customer_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List sales debit notes for a client (firm-scoped — tenant isolation)."""
    try:
        if _USE_MOCK:
            res = [d for d in MOCK_SALES_DEBIT_NOTES if d["client_id"] == client_id and not d.get("deleted_at")]
            if customer_id:
                res = [d for d in res if d.get("customer_id") == customer_id]
            return api_response(True, res)
        from core.supabase_client import get_supabase
        db = get_supabase()
        q = (db.table("sales_debit_notes").select("*")
             .eq("firm_id", current_user.get("firm_id")).eq("client_id", client_id).is_("deleted_at", None))
        if customer_id:
            q = q.eq("customer_id", customer_id)
        return api_response(True, q.order("debit_note_date", desc=True).execute().data or [])
    except Exception as e:
        _logger.error("list_sales_debit_notes: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")


@router.post("/")
def create_sales_debit_note(data: SalesDebitNoteIn, current_user: dict = Depends(rbac("accounting", "write"))):
    """Create a DRAFT sales debit note. Never auto-posts — a human must issue it."""
    try:
        data = data.model_dump()
        firm_id = current_user.get("firm_id")
        client_id = data["client_id"]
        is_interstate = bool(data.get("is_interstate"))
        computed, total_taxable, total_cgst, total_sgst, total_igst = _compute_lines(
            data.get("lines", []), is_interstate)
        total_paise = total_taxable + total_cgst + total_sgst + total_igst
        if total_paise <= 0:
            raise HTTPException(status_code=422, detail="Debit note total must be positive.")
        period_validation_service.validate_posting_date(firm_id or "", data["debit_note_date"])
        fy = _current_fy()

        payload = {
            "firm_id": firm_id, "client_id": client_id, "customer_id": data["customer_id"],
            "sales_invoice_id": data.get("sales_invoice_id"),
            "debit_note_date": data["debit_note_date"], "reason": data.get("reason", ""),
            "is_interstate": is_interstate,
            "taxable_amount_paise": total_taxable, "cgst_paise": total_cgst,
            "sgst_paise": total_sgst, "igst_paise": total_igst, "total_paise": total_paise,
            "total_gst_paise": total_cgst + total_sgst + total_igst,
            "status": "draft", "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if _USE_MOCK:
            payload["id"] = str(uuid.uuid4())
            payload["debit_note_no"] = f"SDN-{fy}-{len([d for d in MOCK_SALES_DEBIT_NOTES if d['client_id']==client_id])+1:04d}"
            MOCK_SALES_DEBIT_NOTES.append(payload)
            return api_response(True, {**payload, "lines": computed})

        from core.supabase_client import get_supabase
        from services.numbering import insert_numbered_document_with_lines
        db = get_supabase()
        sdn = insert_numbered_document_with_lines(
            db, "sales_debit_notes", payload, "debit_note_no",
            lambda s: f"SDN-{fy}-{s:04d}",
            lambda: _next_sdn_seq(db, firm_id, client_id, fy),
            "sales_debit_note_lines", computed, "debit_note_id")
        return api_response(True, {**sdn, "lines": computed})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_sales_debit_note: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")


@router.get("/{sdn_id}")
def get_sales_debit_note(sdn_id: str, current_user: dict = Depends(rbac("accounting", "read"))):
    """Get a single sales debit note with its line items."""
    try:
        if _USE_MOCK:
            d = next((x for x in MOCK_SALES_DEBIT_NOTES if x["id"] == sdn_id and not x.get("deleted_at")), None)
            if not d:
                raise HTTPException(status_code=404, detail=f"Debit note {sdn_id} not found")
            d["lines"] = [ln for ln in MOCK_SALES_DEBIT_NOTE_LINES if ln.get("debit_note_id") == sdn_id]
            return api_response(True, d)
        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = (db.table("sales_debit_notes").select("*").eq("id", sdn_id)
                .eq("firm_id", current_user.get("firm_id")).is_("deleted_at", None).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Debit note {sdn_id} not found")
        d = resp.data[0]
        d["lines"] = db.table("sales_debit_note_lines").select("*").eq("debit_note_id", sdn_id).execute().data or []
        return api_response(True, d)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_sales_debit_note: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")


@router.patch("/{sdn_id}")
def update_sales_debit_note(sdn_id: str, data: SalesDebitNoteUpdateIn, current_user: dict = Depends(rbac("accounting", "write"))):
    """Edit a DRAFT sales debit note — full edit, including lines. Once
    issued, a debit note is immutable like a Sales Invoice past issue; the
    correction path is a fresh note, not an edit (CGST Act §34). notes stays
    editable regardless of status (mirrors sales_invoices' own soft-update
    fields — this router has no attachment concept, matching the Sales
    Invoice baseline, which has none either)."""
    try:
        data = data.model_dump(exclude_none=True)
        lines_data = data.pop("lines", None)
        soft_fields = {"notes"}

        if _USE_MOCK:
            for i, d in enumerate(MOCK_SALES_DEBIT_NOTES):
                if d["id"] == sdn_id and not d.get("deleted_at"):
                    if d.get("status") != "draft" and (set(data.keys()) - soft_fields or lines_data is not None):
                        raise HTTPException(status_code=422, detail="Only a draft debit note can be edited — issue a new debit note to correct an issued one (CGST Act §34).")
                    computed = []
                    if lines_data is not None:
                        is_interstate = data.get("is_interstate", d.get("is_interstate", False))
                        computed, total_taxable, total_cgst, total_sgst, total_igst = _compute_lines(lines_data, is_interstate)
                        total_paise = total_taxable + total_cgst + total_sgst + total_igst
                        if total_paise <= 0:
                            raise HTTPException(status_code=422, detail="Debit note total must be positive.")
                        data.update({
                            "taxable_amount_paise": total_taxable, "cgst_paise": total_cgst,
                            "sgst_paise": total_sgst, "igst_paise": total_igst, "total_paise": total_paise,
                            "total_gst_paise": total_cgst + total_sgst + total_igst,
                        })
                        MOCK_SALES_DEBIT_NOTE_LINES[:] = [l for l in MOCK_SALES_DEBIT_NOTE_LINES if l.get("debit_note_id") != sdn_id]
                        for ln in computed:
                            MOCK_SALES_DEBIT_NOTE_LINES.append({**ln, "debit_note_id": sdn_id})
                    MOCK_SALES_DEBIT_NOTES[i] = {**d, **data}
                    return api_response(True, {**MOCK_SALES_DEBIT_NOTES[i], "lines": computed or [l for l in MOCK_SALES_DEBIT_NOTE_LINES if l.get("debit_note_id") == sdn_id]})
            raise HTTPException(status_code=404, detail=f"Debit note {sdn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = (db.table("sales_debit_notes").select("*")
                .eq("id", sdn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Debit note {sdn_id} not found")
        d = resp.data[0]
        status = d.get("status")
        if status != "draft" and (set(data.keys()) - soft_fields or lines_data is not None):
            raise HTTPException(
                status_code=422,
                detail="Only a draft debit note can be edited — issue a new debit note to correct an issued one (CGST Act §34).",
            )
        if data.get("debit_note_date"):
            period_validation_service.validate_posting_date(firm_id or "", data["debit_note_date"])

        if lines_data is not None:
            is_interstate = data.get("is_interstate", d.get("is_interstate", False))
            computed, total_taxable, total_cgst, total_sgst, total_igst = _compute_lines(lines_data, is_interstate)
            total_paise = total_taxable + total_cgst + total_sgst + total_igst
            if total_paise <= 0:
                raise HTTPException(status_code=422, detail="Debit note total must be positive.")
            data.update({
                "taxable_amount_paise": total_taxable, "cgst_paise": total_cgst,
                "sgst_paise": total_sgst, "igst_paise": total_igst, "total_paise": total_paise,
                "total_gst_paise": total_cgst + total_sgst + total_igst,
            })
            db.table("sales_debit_note_lines").delete().eq("debit_note_id", sdn_id).execute()
            for ln in computed:
                db.table("sales_debit_note_lines").insert({**ln, "debit_note_id": sdn_id}).execute()

        if data:
            upd = db.table("sales_debit_notes").update(data).eq("id", sdn_id).eq("firm_id", firm_id).execute()
            updated = upd.data[0] if upd.data else {**d, **data}
        else:
            updated = d
        lines = (db.table("sales_debit_note_lines").select("*").eq("debit_note_id", sdn_id).execute().data or [])
        return api_response(True, {**updated, "lines": lines})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_sales_debit_note: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")


@router.post("/{sdn_id}/issue")
def issue_sales_debit_note(sdn_id: str, current_user: dict = Depends(rbac("accounting", "write"))):
    """Issue a draft sales debit note: increase the linked invoice's payable in the
    sub-ledger, then post the GL journal. AR sub-ledger, GL AR control and customer
    statement stay reconciled: invoice net outstanding =
    (total + debit_note_paise) - paid - credited. No upper bound — unlike a credit
    note there is nothing to exceed when you're increasing what's owed."""
    try:
        from services.phase2_journal_service import phase2_journal_service
        if _USE_MOCK:
            for i, d in enumerate(MOCK_SALES_DEBIT_NOTES):
                if d["id"] == sdn_id:
                    if d.get("status") != "draft":
                        raise HTTPException(status_code=422, detail="Only draft debit notes can be issued")
                    MOCK_SALES_DEBIT_NOTES[i]["status"] = "issued"
                    return api_response(True, MOCK_SALES_DEBIT_NOTES[i])
            raise HTTPException(status_code=404, detail=f"Debit note {sdn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = db.table("sales_debit_notes").select("*").eq("id", sdn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Debit note {sdn_id} not found")
        sdn = resp.data[0]
        if sdn.get("status") != "draft":
            raise HTTPException(status_code=422, detail="Only draft debit notes can be issued")
        if sdn.get("debit_note_date"):
            period_validation_service.validate_posting_date(firm_id or "", sdn["debit_note_date"])

        client_id = sdn.get("client_id", "")
        sdn_total = int(sdn.get("total_paise") or 0)
        inv_id = sdn.get("sales_invoice_id")

        # ── Apply to the linked invoice's receivable sub-ledger (CGST Act §34(3)),
        # with rollback on failure. No ceiling check — increasing what's owed has
        # no natural upper bound (unlike a credit note capped by net_outstanding).
        prior_inv = None
        if inv_id and sdn_total > 0:
            inv_resp = (db.table("client_sales_invoices")
                        .select("total_paise,paid_paise,credited_paise,debit_note_paise,status")
                        .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute())
            if not inv_resp.data:
                raise HTTPException(status_code=422, detail="Linked invoice is not part of this client's books.")
            inv = inv_resp.data[0]
            if (inv.get("status") or "") in ("draft", "cancelled"):
                raise HTTPException(status_code=422, detail=f"Cannot debit-note a {inv.get('status')} invoice.")
            total = int(inv.get("total_paise") or 0)
            paid = int(inv.get("paid_paise") or 0)
            credited = int(inv.get("credited_paise") or 0)
            prior_debit_note = int(inv.get("debit_note_paise") or 0)
            new_debit_note = prior_debit_note + sdn_total
            effective_total = total + new_debit_note
            settled = paid + credited
            new_status = "paid" if settled >= effective_total else ("partially_paid" if settled > 0 else inv.get("status"))
            prior_inv = {"debit_note_paise": prior_debit_note, "status": inv.get("status")}
            db.table("client_sales_invoices").update({
                "debit_note_paise": new_debit_note, "status": new_status,
            }).eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
            try:
                db.table("sales_debit_note_allocations").insert({
                    "firm_id": firm_id, "debit_note_id": sdn_id,
                    "sales_invoice_id": inv_id, "allocated_paise": sdn_total,
                }).execute()
            except Exception:
                db.table("client_sales_invoices").update({
                    "debit_note_paise": prior_debit_note, "status": prior_inv["status"],
                }).eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
                raise

        # ── Post the GL journal (Dr Trade Receivables / Cr Sales / Cr GST Output).
        # On failure, roll back the sub-ledger application so the books never go
        # partial; the debit note stays a re-tryable draft.
        try:
            journal_id = phase2_journal_service.journal_for_sales_debit_note(
                dn=sdn, firm_id=firm_id or "", client_id=client_id,
            )
            if not journal_id:
                raise RuntimeError("sales debit-note journal posting returned no id")
        except Exception as jerr:
            if prior_inv is not None and inv_id:
                try:
                    db.table("sales_debit_note_allocations").delete().eq("debit_note_id", sdn_id).eq("sales_invoice_id", inv_id).execute()
                    db.table("client_sales_invoices").update({
                        "debit_note_paise": prior_inv["debit_note_paise"], "status": prior_inv["status"],
                    }).eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
                except Exception:
                    pass
            # A deliberate business-rule rejection (e.g. a locked-FY check inside the
            # journal kernel) carries a real, actionable status+message the CA needs —
            # collapsing it into "Please try again" is actively misleading, since
            # retrying identical input will never succeed. Only a genuinely
            # unexpected failure gets the safe generic message.
            if isinstance(jerr, HTTPException):
                _logger.error("issue_sales_debit_note: journal posting failed (HTTP %s); application rolled back: %s",
                               jerr.status_code, jerr.detail)
                raise
            _logger.error("issue_sales_debit_note: journal posting failed; application rolled back: %s", jerr)
            return api_response(False, None, "Unable to issue debit note. Please try again.")

        now_iso = datetime.now(timezone.utc).isoformat()
        applied = sdn_total if (inv_id and sdn_total > 0) else 0
        upd = db.table("sales_debit_notes").update({
            "status": "issued", "journal_entry_id": journal_id, "applied_paise": applied,
        }).eq("id", sdn_id).eq("firm_id", firm_id).execute()
        updated = upd.data[0] if upd.data else {**sdn, "status": "issued", "applied_paise": applied}

        log_event(
            firm_id or "", "sales_debit_note", sdn_id,
            "status_change", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"status": "issued", "journal_entry_id": journal_id, "applied_paise": applied},
        )
        timeline_service.log_timeline_event(
            client_id=client_id, firm_id=firm_id or "", financial_year=_current_fy_long(),
            category="accounting", event_type="sales_debit_note_issued",
            title=f"Debit Note {updated.get('debit_note_no', '')} issued",
            description=f"Sales debit note for ₹{updated.get('total_paise', 0) // 100:,} issued.",
            severity="success", entity_type="sales_debit_note", entity_id=sdn_id,
            amount_paise=updated.get("total_paise"),
            actor_id=current_user.get("auth_user_id"), actor_name=current_user.get("email"),
        )

        updated["journal_entry_id"] = journal_id
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("issue_sales_debit_note: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")


_DELETE_BLOCKED = {"issued": "an issued"}


@router.delete("/{sdn_id}")
def delete_sales_debit_note(sdn_id: str, current_user: dict = Depends(rbac("accounting", "write"))):
    """Hard-delete a DRAFT sales debit note. Only drafts may be deleted — once
    issued they carry a posted journal and have already increased the linked
    invoice's payable (CGST Act §34); removing one outright would corrupt both.
    The row is genuinely removed (not soft-deleted): the create/delete
    audit_log events already capture the full document and a status summary
    respectively, independent of whether the row itself still exists."""
    try:
        if _USE_MOCK:
            for i, d in enumerate(MOCK_SALES_DEBIT_NOTES):
                if d["id"] == sdn_id and not d.get("deleted_at"):
                    st = d.get("status")
                    if st != "draft":
                        raise HTTPException(status_code=422, detail=f"Cannot delete {_DELETE_BLOCKED.get(st, st)} debit note — only drafts can be deleted")
                    MOCK_SALES_DEBIT_NOTES.pop(i)
                    return api_response(True, {"id": sdn_id, "deleted": True})
            raise HTTPException(status_code=404, detail=f"Debit note {sdn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = (db.table("sales_debit_notes").select("*")
                .eq("id", sdn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Debit note {sdn_id} not found")
        d = resp.data[0]
        st = d.get("status")
        if st != "draft":
            raise HTTPException(status_code=422, detail=f"Cannot delete {_DELETE_BLOCKED.get(st, st)} debit note — only drafts can be deleted")

        # Hard delete — draft-only, so sales_debit_note_lines cascades
        # automatically (FK ON DELETE CASCADE); nothing else can reference a
        # still-draft note. The audit_log 'delete' event below (and the
        # 'create' event's full snapshot) survive independently —
        # audit_log.entity_id is a bare text column, not an FK.
        db.table("sales_debit_notes").delete().eq("id", sdn_id).eq("firm_id", firm_id).execute()
        log_event(
            firm_id or "", "sales_debit_note", sdn_id,
            "delete", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            old_data={"debit_note_no": d.get("debit_note_no"), "status": st, "total_paise": d.get("total_paise")},
        )
        return api_response(True, {"id": sdn_id, "deleted": True})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_sales_debit_note: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")
