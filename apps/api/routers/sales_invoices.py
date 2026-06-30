"""Sales invoices — invoice creation with HSN/SAC, GST auto-computation, status tracking.
CGST Act Section 31: Tax invoice requirements.
CGST Act Section 8: Intra-state → CGST+SGST, Inter-state → IGST.
CGST Rule 46: Mandatory fields on tax invoice.
"""
import os
import re
import uuid
import logging
from datetime import datetime, timezone, date, timedelta
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from models.common import api_response
from models.invoices import SalesInvoiceIn, SalesInvoiceUpdateIn
from core.permissions import rbac
from services.audit_service import log_event
from services.period_validation_service import period_validation_service
from services.timeline_service import timeline_service
from services.internal_client_service import is_internal_client, assert_partner_for_internal_id, is_partner
from services.email_service import GENERIC_SEND_FAILURE_MESSAGE

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
    """Return financial year string like '2526' for FY 2025-26 (used in invoice numbering).
    Indian FY runs April 1 – March 31.
    """
    now = datetime.now(timezone.utc)
    if now.month >= 4:
        return f"{str(now.year)[2:]}{str(now.year + 1)[2:]}"
    return f"{str(now.year - 1)[2:]}{str(now.year)[2:]}"


def _current_fy_long() -> str:
    """Return full financial year string like '2025-26' for display/timeline use.
    Indian FY runs April 1 – March 31.
    """
    now = datetime.now(timezone.utc)
    if now.month >= 4:
        start = now.year
    else:
        start = now.year - 1
    end_short = str(start + 1)[2:]
    return f"{start}-{end_short}"


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


def _normalize_desc(description: Optional[str]) -> str:
    """Normalise a line description into a stable lookup key: lower-cased,
    whitespace-collapsed, trimmed. Used to match HSN/SAC suggestions (migration
    101). Pure string handling — no tax/financial meaning."""
    return re.sub(r"\s+", " ", (description or "").strip()).lower()


def _record_hsn_preferences(db, firm_id: str, client_id: str, lines: list[dict]) -> None:
    """Learn the HSN/SAC a firm uses for each line description so the invoice form
    can auto-suggest it next time and reduce manual entry (CGST Rule 46(g): HSN/SAC
    is a mandatory tax-invoice field). The most recently / most frequently chosen
    code surfaces first, so a user override is prioritised on the next invoice.

    Pure UX metadata — this table is NEVER read by any GST, journal, or report
    code. Non-fatal: a failure here must never break an invoice save (same
    contract as the audit logger).
    """
    if not firm_id or not client_id:
        return
    now_iso = datetime.now(timezone.utc).isoformat()
    for ln in lines or []:
        try:
            desc = (ln.get("description") or "").strip()
            hsn = (ln.get("hsn_sac") or "").strip()
            if not desc or not hsn:
                continue
            key = _normalize_desc(desc)
            gst_rate_bps = ln.get("gst_rate_bps")
            existing = (
                db.table("hsn_sac_preferences")
                .select("id,use_count")
                .eq("firm_id", firm_id)
                .eq("client_id", client_id)
                .eq("description_key", key)
                .eq("hsn_sac", hsn)
                .limit(1)
                .execute()
            )
            if existing.data:
                row = existing.data[0]
                db.table("hsn_sac_preferences").update({
                    "use_count":          (row.get("use_count") or 0) + 1,
                    "last_used_at":       now_iso,
                    "sample_description": desc,
                    "gst_rate_bps":       gst_rate_bps,
                }).eq("id", row["id"]).execute()
            else:
                db.table("hsn_sac_preferences").insert({
                    "firm_id":            firm_id,
                    "client_id":          client_id,
                    "description_key":    key,
                    "sample_description": desc,
                    "hsn_sac":            hsn,
                    "gst_rate_bps":       gst_rate_bps,
                    "use_count":          1,
                    "last_used_at":       now_iso,
                }).execute()
        except Exception as e:
            _logger.warning("hsn preference record skipped: %s", e)


def _resolve_creator_name(db, invoice_id: str, created_by: Optional[str]) -> Optional[str]:
    """Best-effort display name for who created an invoice (detail view, UX only).
    Tries the users table by auth_user_id then id; falls back to the 'create'
    audit event's actor_email for legacy rows. Never raises."""
    try:
        if created_by:
            for col in ("auth_user_id", "id"):
                u = (
                    db.table("users").select("full_name,email")
                    .eq(col, created_by).limit(1).execute()
                )
                if u.data:
                    return u.data[0].get("full_name") or u.data[0].get("email")
        a = (
            db.table("audit_log").select("actor_email")
            .eq("entity_id", invoice_id).eq("action", "create")
            .order("created_at").limit(1).execute()
        )
        if a.data:
            return a.data[0].get("actor_email")
    except Exception as e:
        _logger.warning("creator name resolve skipped: %s", e)
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
        return api_response(False, None, "Unable to complete invoice operation. Please try again.")


@router.get("/hsn-suggestions")
def hsn_suggestions(
    client_id: str = Query(...),
    query: str = Query("", description="Partial line description typed by the user"),
    limit: int = Query(5, ge=1, le=20),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Suggest HSN/SAC codes for a line description from the firm's own invoice
    history (migration 101). Ranked by most-recent then most-used, so a code the
    CA picked last time (an override) is prioritised on the next invoice.

    CGST Rule 46(g): HSN/SAC is a mandatory tax-invoice field. This endpoint only
    reduces manual entry — it is never used in any GST or journal computation.
    """
    try:
        firm_id = current_user.get("firm_id", "")
        key = _normalize_desc(query)
        if _USE_MOCK or not key:
            return api_response(True, [])

        from core.supabase_client import get_supabase
        db = get_supabase()
        rows = (
            db.table("hsn_sac_preferences")
            .select("hsn_sac,sample_description,gst_rate_bps,use_count,last_used_at")
            .eq("firm_id", firm_id)
            .eq("client_id", client_id)
            .ilike("description_key", f"%{key}%")
            .order("last_used_at", desc=True)
            .order("use_count", desc=True)
            .limit(limit * 4)
            .execute()
        ).data or []

        # De-dupe by HSN/SAC (rows already ranked; first occurrence wins).
        seen: set[str] = set()
        out: list[dict] = []
        for r in rows:
            h = (r.get("hsn_sac") or "").strip()
            if not h or h in seen:
                continue
            seen.add(h)
            n = r.get("use_count") or 1
            sample = r.get("sample_description") or query
            out.append({
                "hsn_sac":            h,
                "gst_rate_bps":       r.get("gst_rate_bps"),
                "use_count":          n,
                "sample_description": sample,
                "reason":             f"Used in {n} previous {sample} invoice" + ("s" if n != 1 else ""),
            })
            if len(out) >= limit:
                break
        return api_response(True, out)
    except Exception as e:
        _logger.error("hsn_suggestions: %s", e)
        return api_response(False, None, "Unable to fetch HSN suggestions. Please try again.")


@router.get("/")
def list_invoices(
    client_id: str = Query(..., description="CA client ID — required"),
    customer_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, description="Alias for date_from"),
    to_date: Optional[str] = Query(None, description="Alias for date_to"),
    search: Optional[str] = Query(None, description="Match invoice number (case-insensitive)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List sales invoices with optional filters. Soft-deleted drafts are excluded."""
    try:
        # Support both date_from/date_to and from_date/to_date aliases
        effective_from = date_from or from_date
        effective_to = date_to or to_date

        if _USE_MOCK:
            result = [inv for inv in MOCK_SALES_INVOICES
                      if inv["client_id"] == client_id and not inv.get("deleted_at")]
            if customer_id:
                result = [inv for inv in result if inv.get("customer_id") == customer_id]
            if status:
                result = [inv for inv in result if inv.get("status") == status]
            if effective_from:
                result = [inv for inv in result if inv.get("invoice_date", "") >= effective_from]
            if effective_to:
                result = [inv for inv in result if inv.get("invoice_date", "") <= effective_to]
            if search:
                result = [inv for inv in result if search.lower() in inv.get("invoice_no", "").lower()]
            result = result[offset:offset + limit]
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
        if effective_from:
            q = q.gte("invoice_date", effective_from)
        if effective_to:
            q = q.lte("invoice_date", effective_to)
        if search:
            q = q.ilike("invoice_no", f"%{search}%")
        # Exclude soft-deleted drafts (migration 100).
        q = q.is_("deleted_at", None)
        resp = q.order("invoice_date", desc=True).range(offset, offset + limit - 1).execute()
        invoices = resp.data or []

        # Attach lines to each invoice
        for inv in invoices:
            lines_resp = (
                db.table("client_sales_invoice_lines")
                .select("*")
                .eq("sales_invoice_id", inv["id"])
                .execute()
            )
            inv["lines"] = lines_resp.data or []

        return api_response(True, invoices)
    except Exception as e:
        # Full exception + traceback go to server logs only; client sees a generic message.
        _logger.error("list_invoices failed: %s", e, exc_info=True)
        return api_response(False, None, "Unable to complete invoice operation. Please try again.")


_DEFAULT_CREDIT_DAYS = 30  # fallback when neither invoice nor customer sets terms (mirrors collections_service)


def _resolve_credit_terms(
    invoice_date: str,
    due_date: Optional[str],
    credit_days: Optional[int],
    customer_credit_days: Optional[int],
) -> tuple[Optional[str], Optional[int]]:
    """
    Resolve the credit terms to SNAPSHOT onto a new invoice, in priority order:
      1. explicit due_date (kept; credit_days derived from the gap when absent)
      2. explicit credit_days override
      3. the customer's credit_days default
      4. _DEFAULT_CREDIT_DAYS
    Returns (due_date_iso, credit_days). Pure; never raises on malformed input.
    Snapshotting here is what makes a saved invoice immune to later changes to the
    customer's Credit Days.
    """
    try:
        inv_d: Optional[date] = date.fromisoformat(str(invoice_date)[:10])
    except (ValueError, TypeError):
        inv_d = None

    if due_date:
        cd = credit_days
        if cd is None and inv_d is not None:
            try:
                cd = (date.fromisoformat(str(due_date)[:10]) - inv_d).days
            except (ValueError, TypeError):
                cd = None
        return str(due_date)[:10], (int(cd) if cd is not None else None)

    cd = credit_days
    if cd is None:
        cd = customer_credit_days
    if cd is None:
        cd = _DEFAULT_CREDIT_DAYS
    cd = max(0, int(cd))
    due = (inv_d + timedelta(days=cd)).isoformat() if inv_d is not None else None
    return due, cd


def _apply_credit_days_due_date(data: dict, base_invoice_date: Optional[str]) -> None:
    """On a draft edit: when credit_days is set without an explicit due_date,
    recompute due_date from the (new or stored) invoice_date in place, so an edited
    credit period reflects in the stored due date. No-op otherwise."""
    if data.get("credit_days") is None or data.get("due_date"):
        return
    if not base_invoice_date:
        return
    try:
        data["due_date"] = (
            date.fromisoformat(str(base_invoice_date)[:10])
            + timedelta(days=max(0, int(data["credit_days"])))
        ).isoformat()
    except (ValueError, TypeError):
        pass


@router.post("/")
def create_invoice(
    data: SalesInvoiceIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Create a sales invoice with GST auto-computation.
    CGST Act §31: Tax invoice. CGST §8: CGST+SGST (intra), IGST (inter).
    CGST Rule 46: Mandatory fields — invoice_no, date, GSTIN, HSN, tax amounts.
    All monetary values in integer paise.
    """
    try:
        data = data.model_dump()
        lines_data = data.get("lines", [])
        if not lines_data:
            raise HTTPException(status_code=422, detail="At least one line item is required")

        firm_id   = current_user.get("firm_id")
        client_id = data["client_id"]
        supply_state_code = data.get("supply_state_code", "")

        customer: dict = {}
        if _USE_MOCK:
            # In mock mode use is_inter_state flag or derive from place_of_supply vs "27" (Mumbai)
            place = data.get("place_of_supply") or data.get("supply_state_code") or ""
            is_interstate = data.get("is_inter_state", False) or (bool(place) and place != "27")
            client_state_code = "27"
        else:
            from core.supabase_client import get_supabase
            db = get_supabase()

            # Fetch customer state code
            cust_resp = (
                db.table("customers")
                .select("state_code, gstin, credit_days")
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

        if not _USE_MOCK:
            # CGST Act §8: Intra-state if both in same state; inter-state otherwise
            # (In mock mode is_interstate was already determined above from request flags)
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
            # Model uses gst_rate_percent (e.g. 18.0), convert to bps (10000 bps = 100%)
            gst_rate_percent = float(ln.get("gst_rate_percent", 0) or ln.get("gst_rate_bps", 0) / 100)
            gst_rate_bps = int(round(gst_rate_percent * 100))

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

        # Snapshot credit terms onto the invoice. The customer's credit_days is the
        # DEFAULT; an explicit due_date or credit_days on the request overrides it.
        # Storing the resolved values here means later edits to the customer's
        # Credit Days never change this (or any existing) invoice.
        eff_due_date, eff_credit_days = _resolve_credit_terms(
            data["invoice_date"], data.get("due_date"), data.get("credit_days"),
            customer.get("credit_days"),
        )

        # Validate posting date is not in a locked financial year (migration 020)
        period_validation_service.validate_posting_date(firm_id or "", data["invoice_date"])

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
                "due_date":              eff_due_date,
                "credit_days":           eff_credit_days,
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
                "created_by":            current_user.get("auth_user_id"),
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
            "due_date":              eff_due_date,
            "credit_days":           eff_credit_days,
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
            "created_by":            current_user.get("auth_user_id"),
            "created_at":            datetime.now(timezone.utc).isoformat(),
        }

        inv_resp = db.table("client_sales_invoices").insert(invoice_payload).execute()  # type: ignore[possibly-undefined]
        invoice = inv_resp.data[0] if inv_resp.data else invoice_payload
        invoice_id = invoice.get("id", str(uuid.uuid4()))

        # Insert lines
        line_payloads = []
        for ln in computed_lines:
            line_payloads.append({
                # FK column per migration 050 is sales_invoice_id (not invoice_id)
                "sales_invoice_id":      invoice_id,
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
        # Atomicity: PostgREST exposes no multi-statement transaction here, so if
        # the line insert fails we compensate by deleting the just-created header.
        # This guarantees we never leave an orphan invoice (header with no lines).
        try:
            lines_resp = db.table("client_sales_invoice_lines").insert(line_payloads).execute()  # type: ignore[possibly-undefined]
        except Exception:
            db.table("client_sales_invoices").delete().eq("id", invoice_id).execute()  # type: ignore[possibly-undefined]
            raise
        invoice["lines"] = lines_resp.data or computed_lines

        # Learn HSN/SAC choices for smart suggestions (UX only; non-fatal).
        _record_hsn_preferences(db, firm_id or "", client_id, computed_lines)

        log_event(
            firm_id, "sales_invoice", invoice_id,
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=invoice,
        )
        timeline_service.log(
            client_id, "accounting", "Sales Invoice Created",
            f"Invoice {invoice.get('invoice_no', '')} for ₹{invoice.get('total_paise', 0) // 100:,} created (draft)",
            "info", firm_id=firm_id or "",
            entity_type="sales_invoice", entity_id=invoice_id,
            amount_paise=invoice.get("total_paise"), actor_id=current_user.get("auth_user_id"),
        )
        return api_response(True, invoice)
    except HTTPException:
        raise
    except Exception as e:
        # Full exception + traceback go to server logs only; client sees a generic message.
        _logger.error("create_invoice failed: %s", e, exc_info=True)
        return api_response(False, None, "Unable to create invoice. Please try again.")


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
        resp = (
            db.table("client_sales_invoices")
            .select("*, customers(id,name,email,gstin,phone)")
            .eq("id", invoice_id)
            .eq("firm_id", current_user.get("firm_id"))
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        invoice = resp.data[0]
        lines_resp = (
            db.table("client_sales_invoice_lines")
            .select("*")
            .eq("sales_invoice_id", invoice_id)
            .order("sort_order")
            .execute()
        )
        invoice["lines"] = lines_resp.data or []
        # Resolve a human "Created By" for the detail view (UX only). Prefer the
        # users table; fall back to the create event in the audit trail (covers
        # invoices created before created_by was captured). Never fatal.
        invoice["created_by_name"] = _resolve_creator_name(db, invoice_id, invoice.get("created_by"))
        return api_response(True, invoice)
    except HTTPException:
        raise
    except Exception as e:
        # Full exception + traceback go to server logs only; client sees a generic message.
        _logger.error("get_invoice failed: %s", e, exc_info=True)
        return api_response(False, None, "Unable to complete invoice operation. Please try again.")


@router.patch("/{invoice_id}")
def update_invoice(
    invoice_id: str,
    data: SalesInvoiceUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Update a draft invoice. Recomputes GST if lines are changed. Only allowed on draft status."""
    try:
        data = data.model_dump(exclude_none=True)
        # The request model field is is_inter_state; the DB column is is_interstate.
        # Map it so the flag (the form's IGST checkbox) both drives the GST recompute
        # below and persists correctly — without this the column write would 400.
        if "is_inter_state" in data:
            data["is_interstate"] = data.pop("is_inter_state")
        if _USE_MOCK:
            for i, inv in enumerate(MOCK_SALES_INVOICES):
                if inv["id"] == invoice_id:
                    if inv.get("status") != "draft":
                        raise HTTPException(status_code=422, detail="Only draft invoices can be updated")
                    _apply_credit_days_due_date(data, data.get("invoice_date") or inv.get("invoice_date"))
                    MOCK_SALES_INVOICES[i] = {**inv, **data, "updated_at": datetime.now(timezone.utc).isoformat()}
                    return api_response(True, MOCK_SALES_INVOICES[i])
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()

        # Check current status
        resp = db.table("client_sales_invoices").select("status").eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        if resp.data[0]["status"] != "draft":
            raise HTTPException(status_code=422, detail="Only draft invoices can be updated")

        # Recompute due_date from an edited credit period (credit_days set, no
        # explicit due_date). Snapshot stays on the invoice only.
        if data.get("credit_days") is not None and not data.get("due_date"):
            base_date = data.get("invoice_date")
            if not base_date:
                d2 = (db.table("client_sales_invoices").select("invoice_date")
                      .eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute())
                base_date = d2.data[0]["invoice_date"] if d2.data else None
            _apply_credit_days_due_date(data, base_date)

        # If lines are provided, recompute GST
        if "lines" in data:
            # Fetch current invoice for the is_interstate flag. An edit may change
            # it (the IGST checkbox) — honour the new value, else keep the stored
            # one. The GST math (_compute_line_gst) itself is unchanged.
            inv_resp = db.table("client_sales_invoices").select("*").eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
            inv = inv_resp.data[0]
            is_interstate = data.get("is_interstate", inv.get("is_interstate", False))

            computed_lines = []
            total_taxable = 0
            total_cgst    = 0
            total_sgst    = 0
            total_igst    = 0

            for ln in data["lines"]:
                qty          = ln.get("quantity", 1)
                rate_paise   = int(ln.get("rate_paise", 0))
                gst_rate_percent = float(ln.get("gst_rate_percent", 0) or ln.get("gst_rate_bps", 0) / 100)
                gst_rate_bps = int(round(gst_rate_percent * 100))
                taxable      = int(Decimal(str(qty)) * rate_paise)
                cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, is_interstate)

                total_taxable += taxable
                total_cgst    += cgst
                total_sgst    += sgst
                total_igst    += igst

                computed_lines.append({
                    # FK column per migration 050 is sales_invoice_id (not invoice_id)
                    "sales_invoice_id":     invoice_id,
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
            db.table("client_sales_invoice_lines").delete().eq("sales_invoice_id", invoice_id).execute()
            db.table("client_sales_invoice_lines").insert(computed_lines).execute()

            # Learn HSN/SAC choices (incl. overrides) for smart suggestions.
            _record_hsn_preferences(
                db, current_user.get("firm_id", ""), inv.get("client_id", ""), computed_lines
            )

            # Update aggregate totals in invoice
            data.pop("lines")
            data["taxable_amount_paise"] = total_taxable
            data["cgst_paise"]           = total_cgst
            data["sgst_paise"]           = total_sgst
            data["igst_paise"]           = total_igst
            data["total_paise"]          = total_taxable + total_cgst + total_sgst + total_igst

        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        upd_resp = db.table("client_sales_invoices").update(data).eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).execute()
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
        # Full exception + traceback go to server logs only; client sees a generic message.
        _logger.error("update_invoice failed: %s", e, exc_info=True)
        return api_response(False, None, "Unable to complete invoice operation. Please try again.")


@router.post("/{invoice_id}/issue")
def issue_invoice(
    invoice_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Transition invoice from draft → issued.
    ATOMIC (Batch 3.1): the posted journal entry is created FIRST; the invoice
    only becomes 'issued' once the journal succeeds. A posting failure (e.g.
    missing Chart of Accounts) leaves the invoice a re-tryable DRAFT — never an
    issued-but-unposted state.
    CGST Act §31: Invoice must be issued before GST reporting. §9: GST on supply.
    """
    try:
        from services.phase2_journal_service import phase2_journal_service

        if _USE_MOCK:
            for i, inv in enumerate(MOCK_SALES_INVOICES):
                if inv["id"] == invoice_id:
                    if inv.get("status") != "draft":
                        raise HTTPException(status_code=422, detail="Only draft invoices can be issued")
                    # Post journal FIRST — failure keeps the invoice a draft.
                    try:
                        jid = phase2_journal_service.journal_for_sales_invoice(
                            inv, current_user.get("firm_id", ""), inv["client_id"])
                    except ValueError as ve:
                        return api_response(False, None,
                                            f"Cannot issue — {ve} Invoice remains a draft; retry after setup.")
                    MOCK_SALES_INVOICES[i]["status"] = "issued"
                    MOCK_SALES_INVOICES[i]["issued_at"] = datetime.now(timezone.utc).isoformat()
                    MOCK_SALES_INVOICES[i]["journal_entry_id"] = jid or "mock-journal"
                    return api_response(True, MOCK_SALES_INVOICES[i])
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("client_sales_invoices").select("*").eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        inv = resp.data[0]
        if inv.get("status") != "draft":
            raise HTTPException(status_code=422, detail="Only draft invoices can be issued")

        # Auto-create journal entry FIRST — CGST Act §9. If the Chart of Accounts
        # is not set up, this raises ValueError and the invoice stays a draft.
        try:
            journal_id = phase2_journal_service.journal_for_sales_invoice(
                invoice=inv,
                firm_id=current_user.get("firm_id", ""),
                client_id=inv.get("client_id", ""),
            )
        except ValueError as ve:
            return api_response(False, None,
                                f"Cannot issue — {ve} Invoice remains a draft; seed the Chart of Accounts and retry.")
        if not journal_id:
            return api_response(False, None,
                                "Cannot issue — journal posting failed. Invoice remains a draft; retry.")

        now_iso = datetime.now(timezone.utc).isoformat()
        upd = db.table("client_sales_invoices").update({
            "status":           "issued",
            "issued_at":        now_iso,
            "journal_entry_id": journal_id,
        }).eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).execute()
        updated_inv = upd.data[0] if upd.data else {**inv, "status": "issued", "journal_entry_id": journal_id}

        log_event(
            current_user.get("firm_id", ""), "sales_invoice", invoice_id,
            "status_change", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"status": "issued", "journal_entry_id": journal_id},
        )

        # Record timeline event for issued invoice
        timeline_service.log_timeline_event(
            client_id=updated_inv.get("client_id", ""),
            firm_id=current_user.get("firm_id", ""),
            financial_year=_current_fy_long(),
            category="accounting",
            event_type="invoice_posted",
            title=f"Sales Invoice {updated_inv.get('invoice_no', '')} posted",
            description=f"Invoice for ₹{updated_inv.get('total_paise', 0) // 100:,} issued.",
            severity="success",
            entity_type="sales_invoice",
            entity_id=invoice_id,
            amount_paise=updated_inv.get("total_paise"),
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )

        updated_inv["journal_entry_id"] = journal_id
        return api_response(True, updated_inv)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("issue_invoice: %s", e)
        return api_response(False, None, "Unable to complete invoice operation. Please try again.")


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
        resp = db.table("client_sales_invoices").select("status").eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        if resp.data[0]["status"] == "cancelled":
            raise HTTPException(status_code=422, detail="Invoice already cancelled")

        upd = db.table("client_sales_invoices").update({
            "status":       "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).execute()

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
        return api_response(False, None, "Unable to complete invoice operation. Please try again.")


# Human-readable phrasing for statuses that block deletion.
_DELETE_BLOCKED = {
    "issued":         "an issued",
    "partially_paid": "a partially-paid",
    "paid":           "a paid",
    "cancelled":      "a cancelled",
}


@router.delete("/{invoice_id}")
def delete_invoice(
    invoice_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Soft-delete a DRAFT sales invoice.

    Only drafts may be deleted. Issued / partially-paid / paid / cancelled
    invoices are protected — they are legal records (CGST Act §31) with a posted
    journal and must never be removed. Deletion is a soft-delete (sets
    deleted_at, migration 100) plus an immutable audit_log 'delete' event. A draft
    never appears in any accounting report, so removing it has zero effect on the
    Trial Balance / P&L / Balance Sheet.
    """
    try:
        if _USE_MOCK:
            for i, inv in enumerate(MOCK_SALES_INVOICES):
                if inv["id"] == invoice_id:
                    st = inv.get("status")
                    if st != "draft":
                        raise HTTPException(
                            status_code=422,
                            detail=f"Cannot delete {_DELETE_BLOCKED.get(st, st)} invoice — only drafts can be deleted",
                        )
                    MOCK_SALES_INVOICES.pop(i)
                    return api_response(True, {"id": invoice_id, "deleted": True})
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = (
            db.table("client_sales_invoices").select("*")
            .eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).is_("deleted_at", None).limit(1).execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        inv = resp.data[0]
        st = inv.get("status")
        if st != "draft":
            raise HTTPException(
                status_code=422,
                detail=f"Cannot delete {_DELETE_BLOCKED.get(st, st)} invoice — only drafts can be deleted",
            )

        now_iso = datetime.now(timezone.utc).isoformat()
        db.table("client_sales_invoices").update({"deleted_at": now_iso}).eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).execute()

        log_event(
            current_user.get("firm_id", ""), "sales_invoice", invoice_id,
            "delete", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            old_data={
                "invoice_no":  inv.get("invoice_no"),
                "status":      st,
                "total_paise": inv.get("total_paise"),
            },
        )
        return api_response(True, {"id": invoice_id, "deleted": True})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_invoice: %s", e)
        return api_response(False, None, "Unable to complete invoice operation. Please try again.")


# ---------------------------------------------------------------------------
# Batch 3.1 — issued-but-unposted detection + remediation
# ---------------------------------------------------------------------------

@router.get("/maintenance/unposted")
def list_unposted(
    client_id: Optional[str] = Query(None),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List issued-but-unposted invoices (status='issued' AND journal_entry_id IS NULL).
    These are legacy/edge invoices that need a journal reposted. The internal
    practice client's invoices are visible only to Partners (G1)."""
    try:
        firm_id = current_user.get("firm_id", "")
        partner = is_partner(current_user)
        if _USE_MOCK:
            rows = [i for i in MOCK_SALES_INVOICES
                    if i.get("status") == "issued" and not i.get("journal_entry_id")
                    and (client_id is None or i.get("client_id") == client_id)]
        else:
            from core.supabase_client import get_supabase
            db = get_supabase()
            q = (db.table("client_sales_invoices").select("*")
                 .eq("firm_id", firm_id).eq("status", "issued").is_("journal_entry_id", None))
            if client_id:
                q = q.eq("client_id", client_id)
            rows = q.execute().data or []
        # G1: hide the internal client's invoices from non-Partners.
        if not partner:
            rows = [r for r in rows if not is_internal_client(r.get("client_id"), firm_id)]
        return api_response(True, {"unposted": rows, "count": len(rows)})
    except Exception as e:
        _logger.error("list_unposted: %s", e)
        return api_response(False, None, "Unable to complete invoice operation. Please try again.")


@router.post("/{invoice_id}/repost-journal")
def repost_journal(
    invoice_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Remediate an issued-but-unposted invoice by posting its journal.
    Idempotent: if a journal already exists it is reused (_create_journal de-dups
    by reference_no+date+client) and the link is set. Returns the journal id."""
    try:
        from services.phase2_journal_service import phase2_journal_service
        firm_id = current_user.get("firm_id", "")

        if _USE_MOCK:
            inv = next((i for i in MOCK_SALES_INVOICES if i["id"] == invoice_id), None)
            if not inv:
                raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
            assert_partner_for_internal_id(inv.get("client_id"), current_user)
            if inv.get("status") != "issued":
                raise HTTPException(status_code=422, detail="Only issued invoices can be reposted")
            if inv.get("journal_entry_id"):
                return api_response(True, {"invoice_id": invoice_id, "journal_entry_id": inv["journal_entry_id"], "already_posted": True})
            jid = phase2_journal_service.journal_for_sales_invoice(inv, firm_id, inv["client_id"]) or "mock-journal"
            inv["journal_entry_id"] = jid
            return api_response(True, {"invoice_id": invoice_id, "journal_entry_id": jid, "already_posted": False})

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("client_sales_invoices").select("*").eq("id", invoice_id).eq("firm_id", firm_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        inv = resp.data[0]
        assert_partner_for_internal_id(inv.get("client_id"), current_user)
        if inv.get("status") != "issued":
            raise HTTPException(status_code=422, detail="Only issued invoices can be reposted")
        if inv.get("journal_entry_id"):
            return api_response(True, {"invoice_id": invoice_id, "journal_entry_id": inv["journal_entry_id"], "already_posted": True})

        try:
            journal_id = phase2_journal_service.journal_for_sales_invoice(inv, firm_id, inv.get("client_id", ""))
        except ValueError as ve:
            return api_response(False, None, f"Cannot repost — {ve} Seed the Chart of Accounts and retry.")
        if not journal_id:
            return api_response(False, None, "Cannot repost — journal posting failed. Retry after setup.")

        db.table("client_sales_invoices").update({"journal_entry_id": journal_id}).eq("id", invoice_id).eq("firm_id", firm_id).execute()
        log_event(firm_id, "sales_invoice", invoice_id, "repost_journal",
                  actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
                  new_data={"journal_entry_id": journal_id})
        return api_response(True, {"invoice_id": invoice_id, "journal_entry_id": journal_id, "already_posted": False})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("repost_journal: %s", e)
        return api_response(False, None, "Unable to complete invoice operation. Please try again.")


# ---------------------------------------------------------------------------
# Phase 2 — Invoice Delivery
# ---------------------------------------------------------------------------

class _SendInvoiceBody(BaseModel):
    to_email: Optional[str] = None


@router.get("/{invoice_id}/pdf")
def download_sales_invoice_pdf(
    invoice_id: str,
    current_user: dict = Depends(rbac("invoice", "read")),
):
    """Download a GST tax invoice PDF for a client_sales_invoice."""
    from fastapi.responses import Response
    from services.invoice_pdf_service import get_sales_invoice_pdf
    if _USE_MOCK:
        raise HTTPException(status_code=501, detail="PDF not available in mock mode")
    firm_id = current_user.get("firm_id", "")
    try:
        pdf_bytes, filename = get_sales_invoice_pdf(invoice_id, firm_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        _logger.error("download_sales_invoice_pdf %s: %s", invoice_id, e)
        raise HTTPException(status_code=500, detail="PDF generation failed")
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _do_send_invoice(invoice_id: str, body: _SendInvoiceBody, current_user: dict) -> dict:
    """
    Core send logic shared by /send and /resend.
    Creates a new invoice_deliveries row on every call — re-send always appends,
    preserving the full delivery history. Returns the standard API response dict.
    """
    from core.supabase_client import get_supabase
    from services.invoice_pdf_service import get_sales_invoice_pdf
    from services.email_service import send_invoice_to_customer as _send_email

    db = get_supabase()
    firm_id     = current_user.get("firm_id", "")
    actor_id    = current_user.get("auth_user_id")
    actor_email = current_user.get("email")

    # 1. Load invoice — must belong to this firm
    inv_resp = (
        db.table("client_sales_invoices")
        .select("*, customers(id,name,email)")
        .eq("id", invoice_id)
        .eq("firm_id", firm_id)
        .maybe_single()
        .execute()
    )
    if not inv_resp.data:
        raise HTTPException(status_code=404, detail="Invoice not found")
    inv      = inv_resp.data
    customer = inv.get("customers") or {}

    # 2. Status guard: only issued invoices may be sent
    status = inv.get("status", "")
    if status == "draft":
        raise HTTPException(status_code=422, detail="Issue the invoice before sending it")
    if status == "cancelled":
        raise HTTPException(status_code=422, detail="Cannot send a cancelled invoice")

    # 3. Resolve destination email
    to_email = body.to_email or customer.get("email")
    if not to_email:
        raise HTTPException(
            status_code=422,
            detail="No email address available — add one to the customer record or provide it in the request",
        )

    # 4. Validate email format
    try:
        from email_validator import validate_email as _ve, EmailNotValidError
        _ve(to_email, check_deliverability=False)
    except Exception:
        raise HTTPException(status_code=422, detail=f"Invalid email address: {to_email}")

    # 5. Create delivery record (status=sending)
    delivery = (
        db.table("invoice_deliveries")
        .insert({
            "firm_id":       firm_id,
            "client_id":     inv["client_id"],
            "invoice_id":    invoice_id,
            "sent_to":       to_email,
            "sent_by_id":    actor_id,
            "sent_by_email": actor_email,
            "status":        "sending",
        })
        .execute()
    ).data[0]
    delivery_id = delivery["id"]

    # 6. Generate PDF
    try:
        pdf_bytes, pdf_filename = get_sales_invoice_pdf(invoice_id, firm_id)
    except Exception as e:
        _logger.error("PDF gen failed for invoice %s: %s", invoice_id, e)
        db.table("invoice_deliveries").update({
            "status":        "failed",
            "error_message": f"PDF generation failed: {str(e)[:200]}",
        }).eq("id", delivery_id).execute()
        raise HTTPException(status_code=500, detail="PDF generation failed")

    # 7. Load firm name for email body
    firm_row = (
        db.table("firms").select("name").eq("id", firm_id).maybe_single().execute()
    ).data or {}
    firm_name = firm_row.get("name") or "Your Chartered Accountant"

    # 8. Send via Resend
    success, provider_id = _send_email(
        to=to_email,
        customer_name=customer.get("name") or "Customer",
        firm_name=firm_name,
        invoice_no=inv["invoice_no"],
        invoice_date=str(inv["invoice_date"])[:10],
        due_date=str(inv["due_date"])[:10] if inv.get("due_date") else None,
        total_paise=inv.get("total_paise", 0),
        pdf_bytes=pdf_bytes,
        pdf_filename=pdf_filename,
    )

    # 9. Update delivery status
    now_iso = datetime.now(timezone.utc).isoformat()
    update_data: dict = {"status": "sent" if success else "failed"}
    if provider_id:
        update_data["provider_message_id"] = provider_id
    if success:
        update_data["sent_at"] = now_iso
    else:
        update_data["error_message"] = GENERIC_SEND_FAILURE_MESSAGE
    db.table("invoice_deliveries").update(update_data).eq("id", delivery_id).execute()

    # 10. Audit log
    log_event(
        firm_id, "sales_invoice", invoice_id, "send",
        actor_id=actor_id, actor_email=actor_email,
        metadata={
            "sent_to":     to_email,
            "delivery_id": delivery_id,
            "status":      update_data["status"],
        },
    )

    final = (
        db.table("invoice_deliveries").select("*").eq("id", delivery_id).maybe_single().execute()
    ).data
    return {"success": success, "data": final, "error": None if success else GENERIC_SEND_FAILURE_MESSAGE}


@router.post("/{invoice_id}/send")
def send_invoice(
    invoice_id: str,
    body: _SendInvoiceBody,
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """Send an issued sales invoice PDF to the customer by email. Creates a delivery record."""
    if _USE_MOCK:
        return api_response(True, {"status": "sent", "sent_to": body.to_email or "customer@example.com"})
    try:
        return _do_send_invoice(invoice_id, body, current_user)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("send_invoice %s: %s", invoice_id, e)
        return api_response(False, None, "Unable to send invoice. Please try again.")


@router.post("/{invoice_id}/resend")
def resend_invoice(
    invoice_id: str,
    body: _SendInvoiceBody,
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """Re-send an invoice PDF — identical to /send but semantically a resend. Always appends a new delivery record."""
    if _USE_MOCK:
        return api_response(True, {"status": "sent", "sent_to": body.to_email or "customer@example.com"})
    try:
        return _do_send_invoice(invoice_id, body, current_user)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("resend_invoice %s: %s", invoice_id, e)
        return api_response(False, None, "Unable to resend invoice. Please try again.")


@router.get("/{invoice_id}/deliveries")
def list_invoice_deliveries(
    invoice_id: str,
    current_user: dict = Depends(rbac("invoice", "read")),
):
    """List all delivery attempts for an invoice, newest first."""
    if _USE_MOCK:
        return api_response(True, [])
    try:
        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id", "")
        # Verify invoice belongs to this firm before returning delivery records
        exists = (
            db.table("client_sales_invoices")
            .select("id")
            .eq("id", invoice_id)
            .eq("firm_id", firm_id)
            .maybe_single()
            .execute()
        ).data
        if not exists:
            raise HTTPException(status_code=404, detail="Invoice not found")
        rows = (
            db.table("invoice_deliveries")
            .select("*")
            .eq("invoice_id", invoice_id)
            .order("created_at", desc=True)
            .execute()
        ).data or []
        return api_response(True, rows)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("list_invoice_deliveries %s: %s", invoice_id, e)
        return api_response(False, None, "Unable to fetch delivery history. Please try again.")


# ---------------------------------------------------------------------------
# Phase 4.2 — Payment Reminders (collections only — posts no journal, changes
# no accounting figure; reminders reuse invoice_deliveries with kind='reminder').
# ---------------------------------------------------------------------------

@router.post("/{invoice_id}/remind")
def remind_invoice(
    invoice_id: str,
    current_user: dict = Depends(rbac("invoice", "write")),
):
    """Manually send an overdue-payment reminder (with the invoice PDF) to the
    customer. Allowed for any overdue invoice; bypasses the automatic cadence but
    never sends before the invoice is due. Records the send in invoice_deliveries."""
    if _USE_MOCK:
        return api_response(True, {"sent": True, "to": "customer@example.com", "reminder_number": 1})
    from services import collections_service
    try:
        result = collections_service.send_invoice_reminder(
            current_user.get("firm_id", ""), invoice_id,
            actor_id=current_user.get("auth_user_id"))
        return api_response(True, result)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("remind_invoice %s: %s", invoice_id, e)
        return api_response(False, None, "Unable to send reminder. Please try again.")


@router.get("/{invoice_id}/reminders")
def list_invoice_reminders(
    invoice_id: str,
    current_user: dict = Depends(rbac("invoice", "read")),
):
    """List all reminder sends for an invoice, newest first (kind='reminder')."""
    if _USE_MOCK:
        return api_response(True, [])
    from services import collections_service
    try:
        rows = collections_service.invoice_reminder_history(current_user.get("firm_id", ""), invoice_id)
        return api_response(True, rows)
    except Exception as e:
        _logger.error("list_invoice_reminders %s: %s", invoice_id, e)
        return api_response(False, None, "Unable to fetch reminder history. Please try again.")
