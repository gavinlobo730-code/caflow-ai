"""Credit notes — sales returns with GST reversal.
CGST Act Section 34: Credit notes for reduction in taxable value or tax charged.
CGST Act Section 8: Intra-state → CGST+SGST; Inter-state → IGST.
"""
import os
import uuid
import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, field_validator
from models.common import api_response
from models.invoices import InvoiceLineIn
from core.authz import assert_client_access, can_access_client
from core.permissions import rbac
from services.audit_service import log_event
from services.period_validation_service import period_validation_service
from services import period_lock_service
from services.timeline_service import timeline_service
from services.numbering import sequence_after
from core.ist_clock import fy_code, ist_fy_label


class CreditNoteIn(BaseModel):
    client_id: str
    customer_id: str
    credit_note_date: str  # YYYY-MM-DD
    lines: list[InvoiceLineIn]
    sales_invoice_id: str | None = None
    reason: str | None = None
    is_interstate: bool = False

    @field_validator("lines")
    @classmethod
    def at_least_one_line(cls, v: list) -> list:
        if not v:
            raise ValueError("Credit note must have at least one line.")
        return v


class CreditNoteUpdateIn(BaseModel):
    customer_id: str | None = None
    credit_note_date: str | None = None
    sales_invoice_id: str | None = None
    reason: str | None = None
    is_interstate: bool | None = None
    lines: list[InvoiceLineIn] | None = None
    notes: str | None = None


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

def _cn_owner(current_user: dict, cn_id: str) -> tuple[bool, Optional[str]]:
    """`(row_exists, client_id)` for this credit note, firm-scoped.

    Mirrors sales_invoices.py's `_invoice_owner`: returns a pair rather than
    just the id so "no such credit note" and "a credit note with no
    client_id" cannot collapse into one answer.
    """
    if _USE_MOCK:
        cn = next((c for c in MOCK_CREDIT_NOTES if c.get("id") == cn_id), None)
        return (cn is not None, cn.get("client_id") if cn else None)
    from core.supabase_client import get_supabase
    rows = (get_supabase().table("credit_notes").select("client_id")
            .eq("id", cn_id).eq("firm_id", current_user.get("firm_id"))
            .limit(1).execute().data) or []
    return (bool(rows), rows[0].get("client_id") if rows else None)


def _assert_cn_scope(current_user: dict, cn_id: str) -> Optional[str]:
    """404 unless the caller may act on this credit note's client.

    can_access_client (not assert_client_access) and ONE fixed message for
    every failure branch — missing, wrong firm, and right firm but
    unassigned all read identically, so the response cannot be used as an
    oracle for which ids exist (mirrors year_end.py's _assert_engagement_scope).
    """
    found, client_id = _cn_owner(current_user, cn_id)
    if not found or not can_access_client(current_user, client_id):
        raise HTTPException(status_code=404, detail="Credit note not found")
    return client_id




def _next_cn_seq(db, firm_id: str, client_id: str, fy: str) -> int:
    from services.numbering import next_sequence
    return next_sequence(db, "credit_notes", f"CN-{fy}-",
                         firm_id=firm_id, client_id=client_id)


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
    # Full tax first, then split (SGST carries any odd paise) — matches the
    # sales-side fix in routers/sales_invoices.py. A credit note computed with
    # the old floor-each-half split could differ from its invoice's GST by
    # 1 paise per line, leaving a full-value credit note unable to fully
    # reverse its invoice (residue stuck in AR / GST output overstated).
    full_gst = (taxable_paise * gst_rate_bps) // 10000
    cgst = full_gst // 2
    sgst = full_gst - cgst
    return cgst, sgst, 0


def _section_34_2_warning(db, firm_id: str, client_id: str, note_date: str,
                          original_invoice: Optional[dict]) -> Optional[str]:
    """CGST §34(2), measured against the ORIGINAL SUPPLY's financial year.

    Returns the sentence to show the CA, or None. Never raises and never
    refuses: §34(2) bars the tax adjustment, not the document, and a lookup
    that fails must not stop a credit note being raised.
    `domain/gst/credit_note_window.py` holds the rule and the wording.
    """
    from domain.gst.credit_note_window import late_credit_note
    raw_supply = (original_invoice or {}).get("invoice_date")
    if not raw_supply:
        # No linked invoice, so no supply to measure against. Guessing the
        # supply's financial year from the NOTE's date would reproduce the
        # exact error this check exists to catch.
        return None
    try:
        supply = date.fromisoformat(str(raw_supply)[:10])
        note = date.fromisoformat(str(note_date)[:10])
    except (TypeError, ValueError):
        return None
    filed_on = None
    if db is not None:
        try:
            from services.gst_amendment_service import annual_returns_filed_safely
            filed_on = annual_returns_filed_safely(db, firm_id, client_id).get(
                ist_fy_label(supply))
        except Exception:                                          # noqa: BLE001
            # Fail OPEN, deliberately, and for the reason
            # annual_returns_filed_safely already argues: this date SHORTENS the
            # window, so a failed read that shortened it would report a
            # correction as expired when it is not. Without it the 30 November
            # statutory limit still applies, which is the answer the section
            # gives when no annual return has been furnished.
            filed_on = None
    return late_credit_note(note, supply, filed_on)


def _compute_lines(lines_data: list, is_interstate: bool):
    """Shared by create and PATCH — matches debit_notes.py / purchase_credit_notes.py
    / sales_debit_notes.py's own _compute_lines exactly, including "unit":
    ln.get("unit") or "NOS" (those three routers originally omitted it,
    silently dropping every line's unit despite the column, model field and
    editor UI all supporting it — fixed here from the start)."""
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
            # Which Product/Service (goods only, in practice) this return
            # restocks — migration 189. Optional: a line with no pick just
            # never moves stock (domain.inventory_service.apply_credit_note_to_inventory).
            "service_catalogue_id": ln.get("service_catalogue_id"),
        })
    return computed, total_taxable, total_cgst, total_sgst, total_igst


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
    assert_client_access(current_user, client_id)
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
        assert_client_access(current_user, client_id)
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
                    # invoice_date as well as is_interstate: §34(2)'s window runs
                    # from the financial year of the ORIGINAL SUPPLY, so the
                    # supply's own date is the input, not the note's.
                    .select("is_interstate, invoice_date")
                    .eq("id", data["sales_invoice_id"])
                    .eq("firm_id", firm_id)
                    .limit(1)
                    .execute()
                )
                if inv_resp.data:
                    original_invoice = inv_resp.data[0]
                    is_interstate = original_invoice.get("is_interstate", False)

        # Compute lines (shared with the PATCH endpoint — see _compute_lines)
        computed_lines, total_taxable, total_cgst, total_sgst, total_igst = _compute_lines(lines_data, is_interstate)
        total_paise = total_taxable + total_cgst + total_sgst + total_igst
        if total_paise <= 0:
            raise HTTPException(status_code=422, detail="Credit note total must be positive.")

        # Validate posting date is not in a locked financial year (migration 020)
        period_validation_service.validate_posting_date(firm_id or "", data["credit_note_date"])
        # ...and not inside a period whose return has already been filed. The FY
        # lock above is the CA's own switch; this is the portal's. §34(2) allows
        # a credit note to be declared only up to 30 November following the FY
        # or the date GSTR-9 was furnished, and once GSTR-1 for the note's own
        # period is filed that return cannot take it — the reduction goes in a
        # later period's amendment tables instead.
        if not _USE_MOCK:
            from core.supabase_client import get_supabase
            period_lock_service.assert_open(
                get_supabase(), firm_id or "", client_id, data["credit_note_date"])

        # §34(2): CAN THIS NOTE STILL REDUCE THE TAX? A THIRD QUESTION, ABOUT A
        # THIRD PERIOD. The two checks above both ask about the NOTE's own date
        # — is its year locked, is its return filed. §34(2) asks about the
        # SUPPLY's year, which is often a different one and is sometimes closed
        # while the note's own period is wide open: a June 2025 invoice credited
        # in January 2027 sits in an open period and outside a window that shut
        # on 30 November 2026 (SALES-25a).
        #
        # A WARNING, not a refusal. §34(2) bars the tax ADJUSTMENT, not the
        # document — a commercial credit note after the window is lawful, it
        # simply carries no GST. `domain/gst/credit_note_window.py` carries the
        # reasoning and the wording.
        section_34_warning = _section_34_2_warning(
            None if _USE_MOCK else db, firm_id or "", client_id,   # type: ignore[possibly-undefined]
            data["credit_note_date"], original_invoice)

        # The FY of the NUMBER comes from the DOCUMENT'S OWN DATE, not from
        # today (SALES-24). A March-dated document keyed in April used to be
        # numbered into next year's series and sat out of order in the year it
        # belongs to; the lock and period checks above used the document date
        # correctly all along. core.ist_clock.fy_code also fixes the second
        # half of the same line: `datetime.now(timezone.utc)` is still on
        # 31 March between 00:00 and 05:30 IST on 1 April.
        fy = fy_code(data["credit_note_date"])

        if _USE_MOCK:
            seq = sequence_after(
                (cn.get("credit_note_no") for cn in MOCK_CREDIT_NOTES
                 if cn["client_id"] == client_id), f"CN-{fy}-")
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
            # Advisory, and never stored: it describes the moment the note was
            # raised against the supply's own window, not a fact about the row.
            cn["section_34_2_warning"] = section_34_warning
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
        cn["section_34_2_warning"] = section_34_warning
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
    _assert_cn_scope(current_user, cn_id)
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
        # §34(2), DERIVED ON EVERY READ RATHER THAN STORED. It is a function of
        # three dates the books already hold — the supply's, the note's, and the
        # annual return's — so a column would be a cache that goes stale the day
        # GSTR-9 is furnished. Deriving also means the drawer keeps saying it
        # after the toast that first said it has gone.
        supply_row = None
        if cn.get("sales_invoice_id"):
            inv = (db.table("client_sales_invoices").select("invoice_date")
                   .eq("id", cn["sales_invoice_id"])
                   .eq("firm_id", current_user.get("firm_id")).limit(1).execute()).data
            supply_row = inv[0] if inv else None
        cn["section_34_2_warning"] = _section_34_2_warning(
            db, current_user.get("firm_id") or "", cn.get("client_id") or "",
            cn.get("credit_note_date") or "", supply_row)
        return api_response(True, cn)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_credit_note: %s", e)
        return api_response(False, None, "Unable to complete credit note operation. Please try again.")


@router.patch("/{cn_id}")
def update_credit_note(cn_id: str, data: CreditNoteUpdateIn, current_user: dict = Depends(rbac("accounting", "write"))):
    """Edit a DRAFT credit note — full edit, including lines. Once issued, a
    credit note is immutable like a Sales Invoice past issue; the correction
    path is a fresh note, not an edit (CGST Act §34). notes stays editable
    regardless of status (mirrors sales_invoices' own soft-update fields —
    this router has no attachment concept, matching the Sales Invoice
    baseline, which has none either)."""
    _assert_cn_scope(current_user, cn_id)
    try:
        data = data.model_dump(exclude_none=True)
        lines_data = data.pop("lines", None)
        soft_fields = {"notes"}

        if _USE_MOCK:
            for i, c in enumerate(MOCK_CREDIT_NOTES):
                if c["id"] == cn_id and not c.get("deleted_at"):
                    if c.get("status") != "draft" and (set(data.keys()) - soft_fields or lines_data is not None):
                        raise HTTPException(status_code=422, detail="Only a draft credit note can be edited — issue a new credit note to correct an issued one (CGST Act §34).")
                    computed = []
                    if lines_data is not None:
                        is_interstate = data.get("is_interstate", c.get("is_interstate", False))
                        computed, total_taxable, total_cgst, total_sgst, total_igst = _compute_lines(lines_data, is_interstate)
                        total_paise = total_taxable + total_cgst + total_sgst + total_igst
                        if total_paise <= 0:
                            raise HTTPException(status_code=422, detail="Credit note total must be positive.")
                        data.update({
                            "taxable_amount_paise": total_taxable, "cgst_paise": total_cgst,
                            "sgst_paise": total_sgst, "igst_paise": total_igst, "total_paise": total_paise,
                            "total_gst_paise": total_cgst + total_sgst + total_igst,
                        })
                        MOCK_CREDIT_NOTE_LINES[:] = [l for l in MOCK_CREDIT_NOTE_LINES if l.get("credit_note_id") != cn_id]
                        for ln in computed:
                            MOCK_CREDIT_NOTE_LINES.append({**ln, "credit_note_id": cn_id})
                    MOCK_CREDIT_NOTES[i] = {**c, **data}
                    return api_response(True, {**MOCK_CREDIT_NOTES[i], "lines": computed or [l for l in MOCK_CREDIT_NOTE_LINES if l.get("credit_note_id") == cn_id]})
            raise HTTPException(status_code=404, detail=f"Credit note {cn_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = (db.table("credit_notes").select("*")
                .eq("id", cn_id).eq("firm_id", firm_id).is_("deleted_at", None).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Credit note {cn_id} not found")
        c = resp.data[0]
        status = c.get("status")
        if status != "draft" and (set(data.keys()) - soft_fields or lines_data is not None):
            raise HTTPException(
                status_code=422,
                detail="Only a draft credit note can be edited — issue a new credit note to correct an issued one (CGST Act §34).",
            )
        if data.get("credit_note_date"):
            period_validation_service.validate_posting_date(firm_id or "", data["credit_note_date"])
            if not _USE_MOCK:
                from core.supabase_client import get_supabase
                # Both dates: moving a note OUT of a filed period changes that
                # return's figures as much as moving one in.
                period_lock_service.assert_open(
                    get_supabase(), firm_id or "", c.get("client_id"), c.get("credit_note_date"))
                period_lock_service.assert_open(
                    get_supabase(), firm_id or "", c.get("client_id"), data["credit_note_date"])

        if lines_data is not None:
            is_interstate = data.get("is_interstate", c.get("is_interstate", False))
            computed, total_taxable, total_cgst, total_sgst, total_igst = _compute_lines(lines_data, is_interstate)
            total_paise = total_taxable + total_cgst + total_sgst + total_igst
            if total_paise <= 0:
                raise HTTPException(status_code=422, detail="Credit note total must be positive.")
            data.update({
                "taxable_amount_paise": total_taxable, "cgst_paise": total_cgst,
                "sgst_paise": total_sgst, "igst_paise": total_igst, "total_paise": total_paise,
                "total_gst_paise": total_cgst + total_sgst + total_igst,
            })
            db.table("credit_note_lines").delete().eq("credit_note_id", cn_id).execute()
            for ln in computed:
                db.table("credit_note_lines").insert({**ln, "credit_note_id": cn_id}).execute()

        if data:
            upd = db.table("credit_notes").update(data).eq("id", cn_id).eq("firm_id", firm_id).execute()
            updated = upd.data[0] if upd.data else {**c, **data}
        else:
            updated = c
        lines = (db.table("credit_note_lines").select("*").eq("credit_note_id", cn_id).execute().data or [])
        return api_response(True, {**updated, "lines": lines})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_credit_note: %s", e)
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
    _assert_cn_scope(current_user, cn_id)
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
            # Re-checked at ISSUE, not only at create: a draft raised in June
            # and issued in September posts with its June date, and GSTR-1 for
            # June may have been filed in between.
            period_lock_service.assert_open(
                get_supabase(), firm_id or "", cn.get("client_id"), cn["credit_note_date"])

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
        # The supply's own date, for §34(2) below. Kept separately from
        # `prior_inv`, which is a rollback snapshot of exactly the two columns
        # the compensation writes back and must not grow a third.
        supply_invoice: Optional[dict] = None
        if inv_id and cn_total > 0:
            # task #227 audit finding: CAS-guarded (mirrors receipts._adjust_invoice_paid
            # and reversal_service's rollback helpers) — a plain read-then-write here
            # raced with any CONCURRENT credit note issuance against the same invoice,
            # silently losing whichever wrote second (a lost update to credited_paise,
            # not merely a stale-ceiling read the outstanding check alone would catch).
            for _attempt in range(6):
                inv_resp = (db.table("client_sales_invoices")
                            # invoice_date rides along free on a query that is
                            # already made: §34(2)'s window runs from the
                            # ORIGINAL SUPPLY's financial year, and issuing is
                            # when the reduction actually reaches the books.
                            .select("total_paise,paid_paise,credited_paise,debit_note_paise,status,invoice_date")
                            .eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id).limit(1).execute())
                if not inv_resp.data:
                    raise HTTPException(status_code=422, detail="Linked invoice is not part of this client's books.")
                inv = inv_resp.data[0]
                if (inv.get("status") or "") in ("draft", "cancelled"):
                    raise HTTPException(status_code=422, detail=f"Cannot credit a {inv.get('status')} invoice.")
                total       = int(inv.get("total_paise") or 0)
                paid        = int(inv.get("paid_paise") or 0)
                raw_credited = inv.get("credited_paise")   # CAS guard must match this exact stored value
                credited    = int(raw_credited or 0)
                # A sales debit note (CGST Act §34(3)) increases what's receivable
                # before this credit note's own reduction is applied.
                debit_noted = int(inv.get("debit_note_paise") or 0)
                effective_total = total + debit_noted
                net_outstanding = effective_total - paid - credited
                if cn_total > net_outstanding:
                    raise HTTPException(
                        status_code=422,
                        detail=(f"Credit note (₹{cn_total / 100:,.2f}) exceeds the invoice's outstanding "
                                f"(₹{net_outstanding / 100:,.2f})."),
                    )
                new_credited = credited + cn_total
                settled = paid + new_credited
                new_status = "paid" if settled >= effective_total else ("partially_paid" if settled > 0 else inv.get("status"))
                upd = (db.table("client_sales_invoices").update({
                    "credited_paise": new_credited, "status": new_status,
                }).eq("id", inv_id).eq("firm_id", firm_id).eq("client_id", client_id)
                  .eq("credited_paise", raw_credited).execute())
                if upd.data:
                    prior_inv = {"credited_paise": credited, "status": inv.get("status")}
                    supply_invoice = {"invoice_date": inv.get("invoice_date")}
                    break
            else:
                raise HTTPException(status_code=409, detail=f"Invoice {inv_id} is being updated concurrently — please retry.")
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
            # A deliberate business-rule rejection (e.g. period_validation_service's
            # locked-FY check inside the journal kernel) carries a real, actionable
            # status+message the CA needs (e.g. "FY 2025-26 is locked for posting") —
            # collapsing it into "Please try again" is actively misleading, since
            # retrying identical input will never succeed. Only a genuinely
            # unexpected failure gets the safe generic message.
            if isinstance(jerr, HTTPException):
                _logger.error("issue_credit_note: journal posting failed (HTTP %s); application rolled back: %s",
                               jerr.status_code, jerr.detail)
                raise
            _logger.error("issue_credit_note: journal posting failed; application rolled back: %s", jerr)
            return api_response(False, None, "Unable to issue credit note. Please try again.")

        # ── Mark the credit note issued and record how much was applied to invoices.
        now_iso = datetime.now(timezone.utc).isoformat()
        applied = cn_total if (inv_id and cn_total > 0) else 0
        # No issued_at: credit_notes has never had that column, and PostgREST
        # rejects the WHOLE update over one unknown name — so this statement
        # failed every time, AFTER the GL journal above had already posted and
        # committed. A credit note could not be issued: the ledger moved and
        # the document stayed draft. The status flip is the fact, updated_at
        # carries the time, and audit_log records who and when.
        upd = db.table("credit_notes").update({
            "status": "issued", "applied_paise": applied,
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
            financial_year=ist_fy_label(updated_cn.get("credit_note_date")),
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
        # §34(2), said again at the moment it bites. Create warns when the note
        # is drafted; this is when the reduction reaches the ledger and the
        # return, and a draft raised inside the window can be issued outside it.
        # Still a warning: the section bars the tax adjustment, not the document.
        updated_cn["section_34_2_warning"] = _section_34_2_warning(
            db, firm_id or "", client_id, cn.get("credit_note_date") or "", supply_invoice)
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
    """Hard-delete a DRAFT credit note.

    Only drafts may be deleted. Issued/applied credit notes are protected —
    once issued they carry a posted journal and, if linked to an invoice,
    have already reduced that invoice's outstanding balance (CGST Act §34);
    removing one outright would corrupt both. The row is genuinely removed
    (not soft-deleted): the create/delete audit_log events already capture
    the full document and a status summary respectively, independent of
    whether the row itself still exists.
    """
    _assert_cn_scope(current_user, cn_id)
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

        # Hard delete — draft-only, so credit_note_lines cascades automatically
        # (FK ON DELETE CASCADE); nothing else can reference a still-draft
        # note. The audit_log 'delete' event below (and the 'create' event's
        # full snapshot) survive independently — audit_log.entity_id is a
        # bare text column, not an FK.
        db.table("credit_notes").delete().eq("id", cn_id).eq("firm_id", firm_id).execute()

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
