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
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from pydantic import BaseModel, field_validator
from models.common import api_response
from models.invoices import InvoiceLineIn
from core.permissions import rbac
from services.audit_service import log_event
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service

# Same private Storage bucket routers/documents.py and document_intelligence_v1.py
# use — plain attachment (a scanned goods-return note, vendor acknowledgment),
# no AI extraction: a debit note is CA-authored against an existing bill, not
# scanned from an incoming document the way a vendor's purchase invoice is.
_BUCKET = "Documents"


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


class DebitNoteUpdateIn(BaseModel):
    vendor_id: str | None = None
    debit_note_date: str | None = None
    purchase_bill_id: str | None = None
    reason: str | None = None
    is_interstate: bool | None = None
    is_reverse_charge: bool | None = None
    lines: list[InvoiceLineIn] | None = None
    notes: str | None = None
    document_url: str | None = None


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
    # Full tax first, then split (SGST carries any odd paise) — matches the
    # sales-side fix in routers/sales_invoices.py; the old floor-each-half
    # split lost up to 1 paise per line and mis-computed odd-bps rates.
    full_gst = (taxable * gst_rate_bps) // 10000
    cgst = full_gst // 2
    return cgst, full_gst - cgst, 0


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
            "quantity": qty, "unit": ln.get("unit") or "NOS", "rate_paise": rate_paise, "gst_rate_bps": gst_rate_bps,
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


@router.get("/{dn_id}")
def get_debit_note(dn_id: str, current_user: dict = Depends(rbac("accounting", "read"))):
    """Single debit note with its lines — feeds the edit page and detail drawer."""
    try:
        if _USE_MOCK:
            dn = next((d for d in MOCK_DEBIT_NOTES if d["id"] == dn_id and not d.get("deleted_at")), None)
            if not dn:
                raise HTTPException(status_code=404, detail=f"Debit note {dn_id} not found")
            lines = [l for l in MOCK_DEBIT_NOTE_LINES if l.get("debit_note_id") == dn_id]
            return api_response(True, {**dn, "lines": lines})

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = (db.table("debit_notes").select("*")
                .eq("id", dn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Debit note {dn_id} not found")
        dn = resp.data[0]
        lines = (db.table("debit_note_lines").select("*").eq("debit_note_id", dn_id).execute().data or [])
        return api_response(True, {**dn, "lines": lines})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_debit_note: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")


@router.patch("/{dn_id}")
def update_debit_note(dn_id: str, data: DebitNoteUpdateIn, current_user: dict = Depends(rbac("accounting", "write"))):
    """Edit a DRAFT debit note — full edit, including lines. Once issued, a
    debit note is immutable like a Purchase Bill past receipt; the correction
    path is a fresh note, not an edit (CGST Act §34). notes/document_url stay
    editable regardless of status (soft fields — never touch the posted
    GST/AP figures), mirroring purchase_bills.py's draft/locked split."""
    try:
        data = data.model_dump(exclude_none=True)
        lines_data = data.pop("lines", None)
        soft_fields = {"notes", "document_url"}

        if _USE_MOCK:
            for i, dn in enumerate(MOCK_DEBIT_NOTES):
                if dn["id"] == dn_id and not dn.get("deleted_at"):
                    if dn.get("status") != "draft" and (set(data.keys()) - soft_fields or lines_data is not None):
                        raise HTTPException(status_code=422, detail="Only a draft debit note can be edited — issue a new debit note to correct an issued one (CGST Act §34).")
                    computed = []
                    if lines_data is not None:
                        is_interstate = data.get("is_interstate", dn.get("is_interstate", False))
                        computed, total_taxable, total_cgst, total_sgst, total_igst = _compute_lines(lines_data, is_interstate)
                        total_paise = total_taxable + total_cgst + total_sgst + total_igst
                        if total_paise <= 0:
                            raise HTTPException(status_code=422, detail="Debit note total must be positive.")
                        data.update({
                            "taxable_amount_paise": total_taxable, "cgst_paise": total_cgst,
                            "sgst_paise": total_sgst, "igst_paise": total_igst, "total_paise": total_paise,
                            "total_gst_paise": total_cgst + total_sgst + total_igst,
                        })
                        MOCK_DEBIT_NOTE_LINES[:] = [l for l in MOCK_DEBIT_NOTE_LINES if l.get("debit_note_id") != dn_id]
                        for ln in computed:
                            MOCK_DEBIT_NOTE_LINES.append({**ln, "debit_note_id": dn_id})
                    MOCK_DEBIT_NOTES[i] = {**dn, **data}
                    return api_response(True, {**MOCK_DEBIT_NOTES[i], "lines": computed or [l for l in MOCK_DEBIT_NOTE_LINES if l.get("debit_note_id") == dn_id]})
            raise HTTPException(status_code=404, detail=f"Debit note {dn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = (db.table("debit_notes").select("*")
                .eq("id", dn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Debit note {dn_id} not found")
        dn = resp.data[0]
        status = dn.get("status")
        if status != "draft" and (set(data.keys()) - soft_fields or lines_data is not None):
            raise HTTPException(
                status_code=422,
                detail="Only a draft debit note can be edited — issue a new debit note to correct an issued one (CGST Act §34).",
            )
        if data.get("debit_note_date"):
            period_validation_service.validate_posting_date(firm_id or "", data["debit_note_date"])

        if lines_data is not None:
            is_interstate = data.get("is_interstate", dn.get("is_interstate", False))
            computed, total_taxable, total_cgst, total_sgst, total_igst = _compute_lines(lines_data, is_interstate)
            total_paise = total_taxable + total_cgst + total_sgst + total_igst
            if total_paise <= 0:
                raise HTTPException(status_code=422, detail="Debit note total must be positive.")
            data.update({
                "taxable_amount_paise": total_taxable, "cgst_paise": total_cgst,
                "sgst_paise": total_sgst, "igst_paise": total_igst, "total_paise": total_paise,
                "total_gst_paise": total_cgst + total_sgst + total_igst,
            })
            db.table("debit_note_lines").delete().eq("debit_note_id", dn_id).execute()
            for ln in computed:
                db.table("debit_note_lines").insert({**ln, "debit_note_id": dn_id}).execute()

        if data:
            upd = db.table("debit_notes").update(data).eq("id", dn_id).eq("firm_id", firm_id).execute()
            updated = upd.data[0] if upd.data else {**dn, **data}
        else:
            updated = dn
        lines = (db.table("debit_note_lines").select("*").eq("debit_note_id", dn_id).execute().data or [])
        return api_response(True, {**updated, "lines": lines})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_debit_note: %s", e)
        return api_response(False, None, "Unable to complete debit note operation. Please try again.")


@router.post("/upload")
async def upload_debit_note_document(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Plain attachment upload (no AI extraction) — returns a private-bucket
    storage PATH, the same shape purchase_bills.py's document_url stores.
    Mirrors document_intelligence_v1.py's _upload_bill_document."""
    try:
        content = await file.read()
        firm_id = current_user.get("firm_id")
        if _USE_MOCK:
            return api_response(True, {"document_url": f"mock/{firm_id}/{client_id}/debit_note/{uuid.uuid4()}"})

        from core.supabase_client import get_supabase
        db = get_supabase()
        safe_name = (file.filename or "upload").replace("/", "_")
        storage_path = f"{firm_id}/{client_id}/debit_note/{uuid.uuid4()}_{safe_name}"
        db.storage.from_(_BUCKET).upload(
            path=storage_path, file=content,
            file_options={"content-type": file.content_type or "application/octet-stream"},
        )
        return api_response(True, {"document_url": storage_path})
    except Exception as e:
        _logger.error("upload_debit_note_document: %s", e)
        return api_response(False, None, "Unable to upload attachment. Please try again.")


@router.get("/{dn_id}/document-url")
def get_debit_note_document_url(dn_id: str, current_user: dict = Depends(rbac("accounting", "read"))):
    """Mint a fresh signed URL for the note's attachment — document_url is a
    private-bucket storage PATH, not a browser-openable URL. Mirrors
    purchase_bills.py's get_purchase_bill_document_url."""
    try:
        if _USE_MOCK:
            dn = next((d for d in MOCK_DEBIT_NOTES if d["id"] == dn_id), None)
            if not dn:
                raise HTTPException(status_code=404, detail=f"Debit note {dn_id} not found")
            if not dn.get("document_url"):
                raise HTTPException(status_code=404, detail="No document attached to this debit note")
            return api_response(True, {"url": dn["document_url"]})

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("debit_notes").select("document_url").eq("id", dn_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Debit note {dn_id} not found")
        path = resp.data[0].get("document_url")
        if not path:
            raise HTTPException(status_code=404, detail="No document attached to this debit note")
        signed = db.storage.from_(_BUCKET).create_signed_url(path, expires_in=3600)
        url = signed.get("signedURL") if isinstance(signed, dict) else None
        if not url:
            raise HTTPException(status_code=502, detail="Unable to generate a download link. Please try again.")
        return api_response(True, {"url": url})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_debit_note_document_url: %s", e)
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
                 .select("net_payable_paise,paid_paise,debited_paise,credit_note_paise,status")
                 .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute())
            if not b.data:
                raise HTTPException(status_code=422, detail="Linked bill is not part of this client's books.")
            bill = b.data[0]
            if (bill.get("status") or "") in ("draft", "cancelled"):
                raise HTTPException(status_code=422, detail=f"Cannot debit-note a {bill.get('status')} bill.")
            net_payable = int(bill.get("net_payable_paise") or 0)
            paid = int(bill.get("paid_paise") or 0)
            debited = int(bill.get("debited_paise") or 0)
            # A purchase credit note (CGST Act §34(3)) increases what's payable
            # before this debit note's own reduction is applied.
            credit_noted = int(bill.get("credit_note_paise") or 0)
            effective_payable = net_payable + credit_noted
            outstanding = effective_payable - paid - debited
            if dn_total > outstanding:
                raise HTTPException(
                    status_code=422,
                    detail=f"Debit note (₹{dn_total/100:,.2f}) exceeds the bill's outstanding "
                           f"(₹{outstanding/100:,.2f}).")
            prior_bill = {"debited_paise": debited, "status": bill.get("status")}
            new_debited = debited + dn_total
            new_status = "paid" if (paid + new_debited) >= effective_payable else bill.get("status")
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
    """Hard-delete a DRAFT debit note.

    Only drafts may be deleted. Issued debit notes are protected — once
    issued they carry a posted journal and, if linked to a bill, have
    already reduced that bill's payable (CGST Act §34); removing one
    outright would corrupt both. The row is genuinely removed (not
    soft-deleted): the create/delete audit_log events already capture the
    full document and a status summary respectively, independent of
    whether the row itself still exists.
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

        # Hard delete — draft-only, so debit_note_lines cascades automatically
        # (FK ON DELETE CASCADE); nothing else can reference a still-draft note.
        # The audit_log 'delete' event below (and the 'create' event's full
        # snapshot) survive independently — audit_log.entity_id is a bare text
        # column, not an FK.
        db.table("debit_notes").delete().eq("id", dn_id).eq("firm_id", firm_id).execute()

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
