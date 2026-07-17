"""Purchase credit notes — increase to what we owe a vendor (undercharge correction).

The purchase-side mirror of debit_notes.py, for the OTHER direction CGST Act §34
covers: §34(3), where the value/tax charged on the original bill was found to be
LESS than what the vendor should have charged (undercharge, price escalation
after supply, additional charges). A credit note here CREDITS our trade
payable — increases what we owe the vendor — the exact inverse of a (purchase)
debit note.

A purchase credit note increases the linked bill's PAYABLE in the sub-ledger
(credit_note_paise + purchase_credit_note_allocations) and posts a kernel
journal (Dr Purchases / Dr GST Input / Cr Trade Payables) so the AP sub-ledger,
the GL AP control and the vendor statement stay reconciled:
  bill net outstanding = (net_payable_paise + credit_note_paise) - paid_paise - debited_paise.

Unlike a (purchase) debit note, there is no "exceeds outstanding" ceiling on
issue — you can always owe more; the amount just adds to what's still due.

Scope (MVP Phase 1): modelled purely as a financial/GST correction — it does
NOT move inventory (mirrors sales_debit_notes.py's own scope note: the common
real-world case for undercharging is a rate or tax correction, not additional
physical goods received).

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

# Same private Storage bucket routers/documents.py and debit_notes.py use —
# plain attachment, no AI extraction (a credit note is CA-authored, not
# scanned from an incoming document).
_BUCKET = "Documents"


class PurchaseCreditNoteIn(BaseModel):
    client_id: str
    vendor_id: str
    credit_note_date: str  # YYYY-MM-DD
    lines: list[InvoiceLineIn]
    purchase_bill_id: str | None = None
    reason: str | None = None
    is_interstate: bool = False
    is_reverse_charge: bool = False

    @field_validator("lines")
    @classmethod
    def at_least_one_line(cls, v: list) -> list:
        if not v:
            raise ValueError("Credit note must have at least one line.")
        return v


class PurchaseCreditNoteUpdateIn(BaseModel):
    vendor_id: str | None = None
    credit_note_date: str | None = None
    purchase_bill_id: str | None = None
    reason: str | None = None
    is_interstate: bool | None = None
    is_reverse_charge: bool | None = None
    lines: list[InvoiceLineIn] | None = None
    notes: str | None = None
    document_url: str | None = None


_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.purchase_credit_notes")
router = APIRouter(prefix="/api/purchase-credit-notes", tags=["purchase_credit_notes"])

MOCK_PURCHASE_CREDIT_NOTES: list[dict] = []
MOCK_PURCHASE_CREDIT_NOTE_LINES: list[dict] = []


def _current_fy() -> str:
    now = datetime.now(timezone.utc)
    if now.month >= 4:
        return f"{str(now.year)[2:]}{str(now.year + 1)[2:]}"
    return f"{str(now.year - 1)[2:]}{str(now.year)[2:]}"


def _current_fy_long() -> str:
    now = datetime.now(timezone.utc)
    start = now.year if now.month >= 4 else now.year - 1
    return f"{start}-{str(start + 1)[2:]}"


def _next_pcn_seq(db, firm_id: str, client_id: str, fy: str) -> int:
    try:
        resp = (db.table("purchase_credit_notes").select("id", count="exact")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .like("credit_note_no", f"PCN-{fy}-%").execute())
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
def list_purchase_credit_notes(
    client_id: str = Query(..., description="CA client ID — required"),
    vendor_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List purchase credit notes for a client (firm-scoped — tenant isolation)."""
    try:
        if _USE_MOCK:
            res = [d for d in MOCK_PURCHASE_CREDIT_NOTES if d["client_id"] == client_id and not d.get("deleted_at")]
            if vendor_id:
                res = [d for d in res if d.get("vendor_id") == vendor_id]
            return api_response(True, res)
        from core.supabase_client import get_supabase
        db = get_supabase()
        q = (db.table("purchase_credit_notes").select("*")
             .eq("firm_id", current_user.get("firm_id")).eq("client_id", client_id).is_("deleted_at", None))
        if vendor_id:
            q = q.eq("vendor_id", vendor_id)
        return api_response(True, q.order("credit_note_date", desc=True).execute().data or [])
    except Exception as e:
        _logger.error("list_purchase_credit_notes: %s", e)
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")


@router.post("/")
def create_purchase_credit_note(data: PurchaseCreditNoteIn, current_user: dict = Depends(rbac("accounting", "write"))):
    """Create a DRAFT purchase credit note. Never auto-posts — a human must issue it."""
    try:
        data = data.model_dump()
        firm_id = current_user.get("firm_id")
        client_id = data["client_id"]
        is_interstate = bool(data.get("is_interstate"))
        computed, total_taxable, total_cgst, total_sgst, total_igst = _compute_lines(
            data.get("lines", []), is_interstate)
        total_paise = total_taxable + total_cgst + total_sgst + total_igst
        if total_paise <= 0:
            raise HTTPException(status_code=422, detail="Credit note total must be positive.")
        period_validation_service.validate_posting_date(firm_id or "", data["credit_note_date"])
        fy = _current_fy()

        payload = {
            "firm_id": firm_id, "client_id": client_id, "vendor_id": data["vendor_id"],
            "purchase_bill_id": data.get("purchase_bill_id"),
            "credit_note_date": data["credit_note_date"], "reason": data.get("reason", ""),
            "is_interstate": is_interstate, "is_reverse_charge": bool(data.get("is_reverse_charge")),
            "taxable_amount_paise": total_taxable, "cgst_paise": total_cgst,
            "sgst_paise": total_sgst, "igst_paise": total_igst, "total_paise": total_paise,
            "total_gst_paise": total_cgst + total_sgst + total_igst,
            "status": "draft", "created_at": datetime.now(timezone.utc).isoformat(),
        }
        if _USE_MOCK:
            payload["id"] = str(uuid.uuid4())
            payload["credit_note_no"] = f"PCN-{fy}-{len([d for d in MOCK_PURCHASE_CREDIT_NOTES if d['client_id']==client_id])+1:04d}"
            MOCK_PURCHASE_CREDIT_NOTES.append(payload)
            return api_response(True, {**payload, "lines": computed})

        from core.supabase_client import get_supabase
        from services.numbering import insert_numbered_document_with_lines
        db = get_supabase()
        pcn = insert_numbered_document_with_lines(
            db, "purchase_credit_notes", payload, "credit_note_no",
            lambda s: f"PCN-{fy}-{s:04d}",
            lambda: _next_pcn_seq(db, firm_id, client_id, fy),
            "purchase_credit_note_lines", computed, "credit_note_id")
        return api_response(True, {**pcn, "lines": computed})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_purchase_credit_note: %s", e)
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")


@router.get("/{pcn_id}")
def get_purchase_credit_note(pcn_id: str, current_user: dict = Depends(rbac("accounting", "read"))):
    """Get a single purchase credit note with its line items."""
    try:
        if _USE_MOCK:
            d = next((x for x in MOCK_PURCHASE_CREDIT_NOTES if x["id"] == pcn_id and not x.get("deleted_at")), None)
            if not d:
                raise HTTPException(status_code=404, detail=f"Credit note {pcn_id} not found")
            d["lines"] = [ln for ln in MOCK_PURCHASE_CREDIT_NOTE_LINES if ln.get("credit_note_id") == pcn_id]
            return api_response(True, d)
        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = (db.table("purchase_credit_notes").select("*").eq("id", pcn_id)
                .eq("firm_id", current_user.get("firm_id")).is_("deleted_at", None).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Credit note {pcn_id} not found")
        d = resp.data[0]
        d["lines"] = db.table("purchase_credit_note_lines").select("*").eq("credit_note_id", pcn_id).execute().data or []
        return api_response(True, d)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_purchase_credit_note: %s", e)
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")


@router.patch("/{pcn_id}")
def update_purchase_credit_note(pcn_id: str, data: PurchaseCreditNoteUpdateIn, current_user: dict = Depends(rbac("accounting", "write"))):
    """Edit a DRAFT purchase credit note — full edit, including lines. Once
    issued, a credit note is immutable like a Purchase Bill past receipt; the
    correction path is a fresh note, not an edit (CGST Act §34). notes/
    document_url stay editable regardless of status — mirrors debit_notes.py's
    identical draft/locked split."""
    try:
        data = data.model_dump(exclude_none=True)
        lines_data = data.pop("lines", None)
        soft_fields = {"notes", "document_url"}

        if _USE_MOCK:
            for i, d in enumerate(MOCK_PURCHASE_CREDIT_NOTES):
                if d["id"] == pcn_id and not d.get("deleted_at"):
                    if d.get("status") != "draft" and (set(data.keys()) - soft_fields or lines_data is not None):
                        raise HTTPException(status_code=422, detail="Only a draft credit note can be edited — issue a new credit note to correct an issued one (CGST Act §34).")
                    computed = []
                    if lines_data is not None:
                        is_interstate = data.get("is_interstate", d.get("is_interstate", False))
                        computed, total_taxable, total_cgst, total_sgst, total_igst = _compute_lines(lines_data, is_interstate)
                        total_paise = total_taxable + total_cgst + total_sgst + total_igst
                        if total_paise <= 0:
                            raise HTTPException(status_code=422, detail="Credit note total must be positive.")
                        data.update({
                            "taxable_amount_paise": total_taxable, "cgst_paise": total_cgst,
                            "sgst_paise": total_sgst, "igst_paise": total_igst, "total_paise": total_paise,
                            "total_gst_paise": total_cgst + total_sgst + total_igst,
                        })
                        MOCK_PURCHASE_CREDIT_NOTE_LINES[:] = [l for l in MOCK_PURCHASE_CREDIT_NOTE_LINES if l.get("credit_note_id") != pcn_id]
                        for ln in computed:
                            MOCK_PURCHASE_CREDIT_NOTE_LINES.append({**ln, "credit_note_id": pcn_id})
                    MOCK_PURCHASE_CREDIT_NOTES[i] = {**d, **data}
                    return api_response(True, {**MOCK_PURCHASE_CREDIT_NOTES[i], "lines": computed or [l for l in MOCK_PURCHASE_CREDIT_NOTE_LINES if l.get("credit_note_id") == pcn_id]})
            raise HTTPException(status_code=404, detail=f"Credit note {pcn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = (db.table("purchase_credit_notes").select("*")
                .eq("id", pcn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Credit note {pcn_id} not found")
        d = resp.data[0]
        status = d.get("status")
        if status != "draft" and (set(data.keys()) - soft_fields or lines_data is not None):
            raise HTTPException(
                status_code=422,
                detail="Only a draft credit note can be edited — issue a new credit note to correct an issued one (CGST Act §34).",
            )
        if data.get("credit_note_date"):
            period_validation_service.validate_posting_date(firm_id or "", data["credit_note_date"])

        if lines_data is not None:
            is_interstate = data.get("is_interstate", d.get("is_interstate", False))
            computed, total_taxable, total_cgst, total_sgst, total_igst = _compute_lines(lines_data, is_interstate)
            total_paise = total_taxable + total_cgst + total_sgst + total_igst
            if total_paise <= 0:
                raise HTTPException(status_code=422, detail="Credit note total must be positive.")
            data.update({
                "taxable_amount_paise": total_taxable, "cgst_paise": total_cgst,
                "sgst_paise": total_sgst, "igst_paise": total_igst, "total_paise": total_paise,
                "total_gst_paise": total_cgst + total_sgst + total_igst,
            })
            db.table("purchase_credit_note_lines").delete().eq("credit_note_id", pcn_id).execute()
            for ln in computed:
                db.table("purchase_credit_note_lines").insert({**ln, "credit_note_id": pcn_id}).execute()

        if data:
            upd = db.table("purchase_credit_notes").update(data).eq("id", pcn_id).eq("firm_id", firm_id).execute()
            updated = upd.data[0] if upd.data else {**d, **data}
        else:
            updated = d
        lines = (db.table("purchase_credit_note_lines").select("*").eq("credit_note_id", pcn_id).execute().data or [])
        return api_response(True, {**updated, "lines": lines})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_purchase_credit_note: %s", e)
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")


@router.post("/upload")
async def upload_purchase_credit_note_document(
    file: UploadFile = File(...),
    client_id: str = Form(...),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Plain attachment upload (no AI extraction). Mirrors debit_notes.py's
    upload_debit_note_document."""
    try:
        content = await file.read()
        firm_id = current_user.get("firm_id")
        if _USE_MOCK:
            return api_response(True, {"document_url": f"mock/{firm_id}/{client_id}/purchase_credit_note/{uuid.uuid4()}"})

        from core.supabase_client import get_supabase
        db = get_supabase()
        safe_name = (file.filename or "upload").replace("/", "_")
        storage_path = f"{firm_id}/{client_id}/purchase_credit_note/{uuid.uuid4()}_{safe_name}"
        db.storage.from_(_BUCKET).upload(
            path=storage_path, file=content,
            file_options={"content-type": file.content_type or "application/octet-stream"},
        )
        return api_response(True, {"document_url": storage_path})
    except Exception as e:
        _logger.error("upload_purchase_credit_note_document: %s", e)
        return api_response(False, None, "Unable to upload attachment. Please try again.")


@router.get("/{pcn_id}/document-url")
def get_purchase_credit_note_document_url(pcn_id: str, current_user: dict = Depends(rbac("accounting", "read"))):
    """Mint a fresh signed URL for the note's attachment. Mirrors
    debit_notes.py's get_debit_note_document_url."""
    try:
        if _USE_MOCK:
            d = next((x for x in MOCK_PURCHASE_CREDIT_NOTES if x["id"] == pcn_id), None)
            if not d:
                raise HTTPException(status_code=404, detail=f"Credit note {pcn_id} not found")
            if not d.get("document_url"):
                raise HTTPException(status_code=404, detail="No document attached to this credit note")
            return api_response(True, {"url": d["document_url"]})

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("purchase_credit_notes").select("document_url").eq("id", pcn_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Credit note {pcn_id} not found")
        path = resp.data[0].get("document_url")
        if not path:
            raise HTTPException(status_code=404, detail="No document attached to this credit note")
        signed = db.storage.from_(_BUCKET).create_signed_url(path, expires_in=3600)
        url = signed.get("signedURL") if isinstance(signed, dict) else None
        if not url:
            raise HTTPException(status_code=502, detail="Unable to generate a download link. Please try again.")
        return api_response(True, {"url": url})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_purchase_credit_note_document_url: %s", e)
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")


@router.post("/{pcn_id}/issue")
def issue_purchase_credit_note(pcn_id: str, current_user: dict = Depends(rbac("accounting", "write"))):
    """Issue a draft purchase credit note: increase the linked bill's payable in the
    sub-ledger, then post the GL journal. AP sub-ledger, GL AP control and vendor
    statement stay reconciled: bill net outstanding =
    (net_payable + credit_note_paise) - paid - debited. No upper bound — unlike a
    (purchase) debit note there is nothing to exceed when you're increasing what's
    owed."""
    try:
        from services.phase2_journal_service import phase2_journal_service
        if _USE_MOCK:
            for i, d in enumerate(MOCK_PURCHASE_CREDIT_NOTES):
                if d["id"] == pcn_id:
                    if d.get("status") != "draft":
                        raise HTTPException(status_code=422, detail="Only draft credit notes can be issued")
                    MOCK_PURCHASE_CREDIT_NOTES[i]["status"] = "issued"
                    return api_response(True, MOCK_PURCHASE_CREDIT_NOTES[i])
            raise HTTPException(status_code=404, detail=f"Credit note {pcn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = db.table("purchase_credit_notes").select("*").eq("id", pcn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Credit note {pcn_id} not found")
        pcn = resp.data[0]
        if pcn.get("status") != "draft":
            raise HTTPException(status_code=422, detail="Only draft credit notes can be issued")
        if pcn.get("credit_note_date"):
            period_validation_service.validate_posting_date(firm_id or "", pcn["credit_note_date"])

        client_id = pcn.get("client_id", "")
        pcn_total = int(pcn.get("total_paise") or 0)
        bill_id = pcn.get("purchase_bill_id")

        # ── Apply to the linked bill's payable sub-ledger (CGST Act §34(3)),
        # with rollback on failure. No ceiling check — increasing what's owed
        # has no natural upper bound (unlike a debit note capped by outstanding).
        prior_bill = None
        if bill_id and pcn_total > 0:
            b = (db.table("purchase_bills")
                 .select("net_payable_paise,paid_paise,debited_paise,credit_note_paise,status")
                 .eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute())
            if not b.data:
                raise HTTPException(status_code=422, detail="Linked bill is not part of this client's books.")
            bill = b.data[0]
            if (bill.get("status") or "") in ("draft", "cancelled"):
                raise HTTPException(status_code=422, detail=f"Cannot credit-note a {bill.get('status')} bill.")
            net_payable = int(bill.get("net_payable_paise") or 0)
            paid = int(bill.get("paid_paise") or 0)
            debited = int(bill.get("debited_paise") or 0)
            prior_credit_note = int(bill.get("credit_note_paise") or 0)
            new_credit_note = prior_credit_note + pcn_total
            effective_payable = net_payable + new_credit_note
            settled = paid + debited
            new_status = "paid" if settled >= effective_payable else ("partially_paid" if settled > 0 else bill.get("status"))
            prior_bill = {"credit_note_paise": prior_credit_note, "status": bill.get("status")}
            db.table("purchase_bills").update({
                "credit_note_paise": new_credit_note, "status": new_status,
            }).eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
            try:
                db.table("purchase_credit_note_allocations").insert({
                    "firm_id": firm_id, "credit_note_id": pcn_id,
                    "purchase_bill_id": bill_id, "allocated_paise": pcn_total,
                }).execute()
            except Exception:
                db.table("purchase_bills").update({
                    "credit_note_paise": prior_credit_note, "status": prior_bill["status"],
                }).eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
                raise

        # ── Post the GL journal (Dr Purchases / Dr GST Input / Cr Trade Payables).
        # On failure, roll back the sub-ledger application so the books never go
        # partial; the credit note stays a re-tryable draft.
        try:
            journal_id = phase2_journal_service.journal_for_purchase_credit_note(
                cn=pcn, firm_id=firm_id or "", client_id=client_id,
            )
            if not journal_id:
                raise RuntimeError("purchase credit-note journal posting returned no id")
        except Exception as jerr:
            if prior_bill is not None and bill_id:
                try:
                    db.table("purchase_credit_note_allocations").delete().eq("credit_note_id", pcn_id).eq("purchase_bill_id", bill_id).execute()
                    db.table("purchase_bills").update({
                        "credit_note_paise": prior_bill["credit_note_paise"], "status": prior_bill["status"],
                    }).eq("id", bill_id).eq("firm_id", firm_id).eq("client_id", client_id).execute()
                except Exception:
                    pass
            _logger.error("issue_purchase_credit_note: journal posting failed; application rolled back: %s", jerr)
            return api_response(False, None, "Unable to issue credit note. Please try again.")

        applied = pcn_total if (bill_id and pcn_total > 0) else 0
        upd = db.table("purchase_credit_notes").update({
            "status": "issued", "journal_entry_id": journal_id, "applied_paise": applied,
        }).eq("id", pcn_id).eq("firm_id", firm_id).execute()
        updated = upd.data[0] if upd.data else {**pcn, "status": "issued", "applied_paise": applied}

        log_event(
            firm_id or "", "purchase_credit_note", pcn_id,
            "status_change", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"status": "issued", "journal_entry_id": journal_id, "applied_paise": applied},
        )
        timeline_service.log_timeline_event(
            client_id=client_id, firm_id=firm_id or "", financial_year=_current_fy_long(),
            category="accounting", event_type="purchase_credit_note_issued",
            title=f"Credit Note {updated.get('credit_note_no', '')} issued",
            description=f"Purchase credit note for ₹{updated.get('total_paise', 0) // 100:,} issued.",
            severity="success", entity_type="purchase_credit_note", entity_id=pcn_id,
            amount_paise=updated.get("total_paise"),
            actor_id=current_user.get("auth_user_id"), actor_name=current_user.get("email"),
        )

        updated["journal_entry_id"] = journal_id
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("issue_purchase_credit_note: %s", e)
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")


_DELETE_BLOCKED = {"issued": "an issued"}


@router.delete("/{pcn_id}")
def delete_purchase_credit_note(pcn_id: str, current_user: dict = Depends(rbac("accounting", "write"))):
    """Hard-delete a DRAFT purchase credit note. Only drafts may be deleted — once
    issued they carry a posted journal and have already increased the linked
    bill's payable (CGST Act §34); removing one outright would corrupt both.
    The row is genuinely removed (not soft-deleted): the create/delete
    audit_log events already capture the full document and a status summary
    respectively, independent of whether the row itself still exists."""
    try:
        if _USE_MOCK:
            for i, d in enumerate(MOCK_PURCHASE_CREDIT_NOTES):
                if d["id"] == pcn_id and not d.get("deleted_at"):
                    st = d.get("status")
                    if st != "draft":
                        raise HTTPException(status_code=422, detail=f"Cannot delete {_DELETE_BLOCKED.get(st, st)} credit note — only drafts can be deleted")
                    MOCK_PURCHASE_CREDIT_NOTES.pop(i)
                    return api_response(True, {"id": pcn_id, "deleted": True})
            raise HTTPException(status_code=404, detail=f"Credit note {pcn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = (db.table("purchase_credit_notes").select("*")
                .eq("id", pcn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Credit note {pcn_id} not found")
        d = resp.data[0]
        st = d.get("status")
        if st != "draft":
            raise HTTPException(status_code=422, detail=f"Cannot delete {_DELETE_BLOCKED.get(st, st)} credit note — only drafts can be deleted")

        # Hard delete — draft-only, so purchase_credit_note_lines cascades
        # automatically (FK ON DELETE CASCADE); nothing else can reference a
        # still-draft note. The audit_log 'delete' event below (and the
        # 'create' event's full snapshot) survive independently —
        # audit_log.entity_id is a bare text column, not an FK.
        db.table("purchase_credit_notes").delete().eq("id", pcn_id).eq("firm_id", firm_id).execute()
        log_event(
            firm_id or "", "purchase_credit_note", pcn_id,
            "delete", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            old_data={"credit_note_no": d.get("credit_note_no"), "status": st, "total_paise": d.get("total_paise")},
        )
        return api_response(True, {"id": pcn_id, "deleted": True})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_purchase_credit_note: %s", e)
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")
