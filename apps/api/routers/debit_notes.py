"""Debit notes — vendor purchase returns with GST (ITC) reversal.

The AP-side mirror of credit_notes.py. A debit note reduces a purchase bill's
PAYABLE in the sub-ledger (debited_paise + debit_note_allocations) and posts a
kernel journal (Dr Trade Payables / Cr Purchases / Cr GST Input) so the AP
sub-ledger, the GL AP control and the vendor statement stay reconciled.

CGST Act Section 34: debit/credit notes for change in taxable value or tax.
CGST Act Section 8: Intra-state → CGST+SGST; Inter-state → IGST.
Integer paise throughout.
"""
import os
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


class DebitNoteIn(BaseModel):
    client_id: str
    vendor_id: str
    debit_note_date: str  # YYYY-MM-DD
    lines: list[InvoiceLineIn]
    purchase_bill_id: str | None = None
    reason: str | None = None
    is_interstate: bool = False
    is_reverse_charge: bool = False

    @field_validator("lines")
    @classmethod
    def at_least_one_line(cls, v: list) -> list:
        if not v:
            raise ValueError("Debit note must have at least one line.")
        return v


_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.debit_notes")
router = APIRouter(prefix="/api/debit-notes", tags=["debit_notes"])

MOCK_DEBIT_NOTES: list[dict] = []
MOCK_DEBIT_NOTE_LINES: list[dict] = []


def _current_fy() -> str:
    now = datetime.now(timezone.utc)
    if now.month >= 4:
        return f"{str(now.year)[2:]}{str(now.year + 1)[2:]}"
    return f"{str(now.year - 1)[2:]}{str(now.year)[2:]}"


def _current_fy_long() -> str:
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def _compute_line_gst(taxable: int, gst_rate_bps: int, is_interstate: bool) -> tuple[int, int, int]:
    if is_interstate:
        return 0, 0, (taxable * gst_rate_bps) // 10000
    half = gst_rate_bps // 2
    return (taxable * half) // 10000, (taxable * half) // 10000, 0


def _next_dn_seq(db, firm_id: str, client_id: str, fy: str) -> int:
    try:
        resp = (db.table("debit_notes").select("id", count="exact")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .like("debit_note_no", f"DN-{fy}-%").execute())
        return (resp.count or 0) + 1
    except Exception:
        return 1


def _compute_lines(lines_data: list, is_interstate: bool):
    computed, total_taxable, total_cgst, total_sgst, total_igst = [], 0, 0, 0, 0
    for ln in lines_data:
        ln = ln if isinstance(ln, dict) else ln.model_dump()
        qty = ln.get("quantity", 1)
        rate_paise = int(ln.get("rate_paise", 0))
        # Derive bps from gst_rate_percent (fall back to explicit bps) — same as invoices.
        gst_rate_bps = int(ln.get("gst_rate_bps") or 0)
        if not gst_rate_bps and ln.get("gst_rate_percent"):
            gst_rate_bps = int(round(float(ln.get("gst_rate_percent")) * 100))
        taxable = int(Decimal(str(qty)) * rate_paise)
        cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, is_interstate)
        total_taxable += taxable; total_cgst += cgst; total_sgst += sgst; total_igst += igst
        computed.append({
            "description": ln.get("description", ""), "hsn_sac": ln.get("hsn_sac", ""),
            "quantity": qty, "rate_paise": rate_paise, "gst_rate_bps": gst_rate_bps,
            "taxable_amount_paise": taxable, "cgst_paise": cgst, "sgst_paise": sgst,
            "igst_paise": igst, "line_total_paise": taxable + cgst + sgst + igst,
            # Which Product/Service (goods only, in practice) this return
            # de-stocks — migration 189. Optional: unset just means this line
            # never moves stock (domain.inventory_service.apply_debit_note_to_inventory).
            "service_catalogue_id": ln.get("service_catalogue_id"),
        })
    return computed, total_taxable, total_cgst, total_sgst, total_igst


@router.get("/")
def list_debit_notes(
    client_id: str = Query(..., description="CA client ID — required"),
    vendor_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List debit notes for a client (firm-scoped — tenant isolation)."""
    try:
        if _USE_MOCK:
            res = [d for d in MOCK_DEBIT_NOTES if d["client_id"] == client_id and not d.get("deleted_at")]
            if vendor_id:
                res = [d for d in res if d.get("vendor_id") == vendor_id]
            return api_response(True, res)
        from core.supabase_client import get_supabase
        db = get_supabase()
        q = (db.table("debit_notes").select("*")
             .eq("firm_id", current_user.get("firm_id")).eq("client_id", client_id).is_("deleted_at", None))
        if vendor_id:
            q = q.eq("vendor_id", vendor_id)
        return api_response(True, q.order("debit_note_date", desc=True).execute().data or [])
    except Exception as e:
        _logger.error("list_debit_notes: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")


@router.post("/")
def create_debit_note(data: DebitNoteIn, current_user: dict = Depends(rbac("accounting", "write"))):
    """Create a DRAFT debit note. Never auto-posts — a human must issue it."""
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
            "firm_id": firm_id, "client_id": client_id, "vendor_id": data["vendor_id"],
            "purchase_bill_id": data.get("purchase_bill_id"),
            "debit_note_date": data["debit_note_date"], "reason": data.get("reason", ""),
            "is_interstate": is_interstate, "is_reverse_charge": bool(data.get("is_reverse_charge")),
            "taxable_amount_paise": total_taxable, "cgst_paise": total_cgst,
            "sgst_paise": total_sgst, "igst_paise": total_igst, "total_paise": total_paise,
            "total_gst_paise": total_cgst + total_sgst + total_igst,
            "status": "draft", "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if _USE_MOCK:
            import uuid
            payload["id"] = str(uuid.uuid4())
            payload["debit_note_no"] = f"DN-{fy}-{len([d for d in MOCK_DEBIT_NOTES if d['client_id']==client_id])+1:04d}"
            MOCK_DEBIT_NOTES.append(payload)
            return api_response(True, {**payload, "lines": computed})

        from core.supabase_client import get_supabase
        from services.numbering import insert_numbered_document_with_lines
        db = get_supabase()
        dn = insert_numbered_document_with_lines(
            db, "debit_notes", payload, "debit_note_no",
            lambda s: f"DN-{fy}-{s:04d}",
            lambda: _next_dn_seq(db, firm_id, client_id, fy),
            "debit_note_lines", computed, "debit_note_id")
        return api_response(True, {**dn, "lines": computed})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_debit_note: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")


@router.post("/{dn_id}/issue")
def issue_debit_note(dn_id: str, current_user: dict = Depends(rbac("accounting", "write"))):
    """Issue a draft debit note: relieve the linked bill's payable in the sub-ledger,
    then post the GL journal. AP sub-ledger, GL AP control and vendor statement stay
    reconciled: bill net outstanding = net_payable − paid − debited."""
    try:
        from services.phase2_journal_service import phase2_journal_service
        if _USE_MOCK:
            for i, dn in enumerate(MOCK_DEBIT_NOTES):
                if dn["id"] == dn_id:
                    if dn.get("status") != "draft":
                        raise HTTPException(status_code=422, detail="Only draft debit notes can be issued")
                    MOCK_DEBIT_NOTES[i]["status"] = "issued"
                    return api_response(True, MOCK_DEBIT_NOTES[i])
            raise HTTPException(status_code=404, detail=f"Debit note {dn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = db.table("debit_notes").select("*").eq("id", dn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Debit note {dn_id} not found")
        dn = resp.data[0]
        if dn.get("status") != "draft":
            raise HTTPException(status_code=422, detail="Only draft debit notes can be issued")
        if dn.get("debit_note_date"):
            period_validation_service.validate_posting_date(firm_id or "", dn["debit_note_date"])

        client_id = dn.get("client_id", "")
        dn_total = int(dn.get("total_paise") or 0)
        bill_id = dn.get("purchase_bill_id")

        # ── Apply to the linked bill's payable sub-ledger (CGST Act §34), with rollback. ──
        prior_bill = None
        if bill_id and dn_total > 0:
            b = (db.table("purchase_bills")
                 .select("net_payable_paise,paid_paise,debited_paise,status")
                 .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute())
            if not b.data:
                raise HTTPException(status_code=422, detail="Linked bill is not part of this client's books.")
            bill = b.data[0]
            if (bill.get("status") or "") in ("draft", "cancelled"):
                raise HTTPException(status_code=422, detail=f"Cannot debit-note a {bill.get('status')} bill.")
            net_payable = int(bill.get("net_payable_paise") or 0)
            paid = int(bill.get("paid_paise") or 0)
            debited = int(bill.get("debited_paise") or 0)
            outstanding = net_payable - paid - debited
            if dn_total > outstanding:
                raise HTTPException(
                    status_code=422,
                    detail=f"Debit note (₹{dn_total/100:,.2f}) exceeds the bill's outstanding "
                           f"(₹{outstanding/100:,.2f}).")
            prior_bill = {"debited_paise": debited, "status": bill.get("status")}
            new_debited = debited + dn_total
            new_status = "paid" if (paid + new_debited) >= net_payable else bill.get("status")
            db.table("purchase_bills").update({"debited_paise": new_debited, "status": new_status}) \
                .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
            try:
                db.table("debit_note_allocations").insert({
                    "firm_id": firm_id, "debit_note_id": dn_id,
                    "purchase_bill_id": bill_id, "allocated_paise": dn_total,
                }).execute()
            except Exception:
                db.table("purchase_bills").update(
                    {"debited_paise": debited, "status": prior_bill["status"]}) \
                    .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
                raise

        # ── Post the GL journal; roll back the sub-ledger on failure. ──
        try:
            journal_id = phase2_journal_service.journal_for_debit_note(dn, firm_id or "", client_id)
            if not journal_id:
                raise RuntimeError("debit-note journal posting returned no id")
        except Exception as jerr:
            if prior_bill is not None and bill_id:
                try:
                    db.table("debit_note_allocations").delete().eq("debit_note_id", dn_id).eq("purchase_bill_id", bill_id).execute()
                    db.table("purchase_bills").update(
                        {"debited_paise": prior_bill["debited_paise"], "status": prior_bill["status"]}) \
                        .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
                except Exception:
                    pass
            _logger.error("issue_debit_note: journal failed; application rolled back: %s", jerr)
            return api_response(False, None, "Unable to issue debit note. Please try again.")

        applied = dn_total if (bill_id and dn_total > 0) else 0
        upd = db.table("debit_notes").update({
            "status": "issued", "journal_entry_id": journal_id, "applied_paise": applied,
        }).eq("id", dn_id).eq("firm_id", firm_id).execute()
        updated = upd.data[0] if upd.data else {**dn, "status": "issued"}
        log_event(firm_id or "", "debit_note", dn_id, "status_change",
                  actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
                  new_data={"status": "issued", "journal_entry_id": journal_id, "applied_paise": applied})
        timeline_service.log_timeline_event(
            client_id=client_id, firm_id=firm_id or "", financial_year=_current_fy_long(),
            category="accounting", event_type="debit_note_issued",
            title=f"Debit Note {updated.get('debit_note_no', '')} issued",
            description=f"Debit note for ₹{updated.get('total_paise', 0)//100:,} issued.",
            severity="success", entity_type="debit_note", entity_id=dn_id,
            amount_paise=updated.get("total_paise"),
            actor_id=current_user.get("auth_user_id"), actor_name=current_user.get("email"))

        # Inventory: purchase return — goods physically leave stock (goods
        # lines only). Runs AFTER issuance and the AP/GL effects above have
        # committed — never blocks issuing the debit note.
        try:
            from domain.inventory_service import apply_debit_note_to_inventory
            apply_debit_note_to_inventory(
                db, firm_id=firm_id or "", client_id=client_id,
                # journal_entries.created_by FK references users(id), not auth_user_id.
                debit_note=updated, created_by=current_user.get("id"),
            )
        except Exception as e:
            _logger.error("issue_debit_note: inventory apply failed for %s: %s", dn_id, e, exc_info=True)

        updated["journal_entry_id"] = journal_id
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("issue_debit_note: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")


# Human-readable phrasing for statuses that block deletion.
_DELETE_BLOCKED = {"issued": "an issued"}


@router.delete("/{dn_id}")
def delete_debit_note(
    dn_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Soft-delete a DRAFT debit note.

    Only drafts may be deleted. Issued debit notes are protected — once
    issued they carry a posted journal and, if linked to a bill, have
    already reduced that bill's payable (CGST Act §34); removing one
    outright would corrupt both. Deletion is a soft-delete (sets
    deleted_at, migration 183) plus an immutable audit_log 'delete' event,
    mirroring sales_invoices.delete_invoice exactly.
    """
    try:
        if _USE_MOCK:
            for i, dn in enumerate(MOCK_DEBIT_NOTES):
                if dn["id"] == dn_id and not dn.get("deleted_at"):
                    st = dn.get("status")
                    if st != "draft":
                        raise HTTPException(
                            status_code=422,
                            detail=f"Cannot delete {_DELETE_BLOCKED.get(st, st)} debit note — only drafts can be deleted",
                        )
                    MOCK_DEBIT_NOTES.pop(i)
                    return api_response(True, {"id": dn_id, "deleted": True})
            raise HTTPException(status_code=404, detail=f"Debit note {dn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = (
            db.table("debit_notes").select("*")
            .eq("id", dn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Debit note {dn_id} not found")
        dn = resp.data[0]
        st = dn.get("status")
        if st != "draft":
            raise HTTPException(
                status_code=422,
                detail=f"Cannot delete {_DELETE_BLOCKED.get(st, st)} debit note — only drafts can be deleted",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        db.table("debit_notes").update({"deleted_at": now_iso}).eq("id", dn_id).eq("firm_id", firm_id).execute()

        log_event(
            firm_id or "", "debit_note", dn_id,
            "delete", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            old_data={
                "debit_note_no": dn.get("debit_note_no"),
                "status":        st,
                "total_paise":   dn.get("total_paise"),
            },
        )
        return api_response(True, {"id": dn_id, "deleted": True})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_debit_note: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")
