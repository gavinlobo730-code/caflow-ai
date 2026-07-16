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
from pydantic import BaseModel, ValidationError as PydanticValidationError
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


def _assert_invoice_no_available(
    db, firm_id: str, client_id: str, invoice_no: str, exclude_id: Optional[str] = None,
) -> None:
    """Reject a duplicate invoice number for this client. Numbering is fully
    manual (the CA types it — no Caflow-generated scheme), so a collision is a
    genuine user mistake, not a numbering race: fail fast with a clear message
    rather than the graceful-retry-with-a-different-number pattern
    services/numbering.py uses for auto-generated document numbers.
    CGST Rule 46(b) requires uniqueness only within a financial year; Caflow
    enforces the stricter "unique for this client, full stop" — a partial
    unique index on (firm_id, client_id, invoice_no) WHERE deleted_at IS NULL
    (migration 151 added the constraint; migration 209 made it partial once
    soft-delete existed, so a deleted invoice's number is free to reuse).
    """
    # deleted_at IS NULL — a soft-deleted invoice (e.g. an abandoned draft the
    # CA deleted) is invisible everywhere in the UI, but without this filter
    # its invoice_no stayed permanently blocked: the CA deletes draft "00002",
    # tries to reuse "00002" for a real invoice later, and gets a 409 for a
    # number the app shows nowhere as taken. The DB-level UNIQUE constraint is
    # a partial index with the same WHERE clause (migration 209) so this stays
    # true even on a concurrent-race fallback.
    if _USE_MOCK:
        for inv in MOCK_SALES_INVOICES:
            if (inv.get("firm_id") == firm_id and inv.get("client_id") == client_id
                    and inv.get("invoice_no") == invoice_no and inv.get("id") != exclude_id
                    and not inv.get("deleted_at")):
                raise HTTPException(status_code=409, detail=f"Invoice number '{invoice_no}' already exists for this client.")
        return
    q = (
        db.table("client_sales_invoices").select("id")
        .eq("firm_id", firm_id).eq("client_id", client_id).eq("invoice_no", invoice_no)
        .is_("deleted_at", "null")
    )
    if exclude_id:
        q = q.neq("id", exclude_id)
    if q.limit(1).execute().data:
        raise HTTPException(status_code=409, detail=f"Invoice number '{invoice_no}' already exists for this client.")


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
        # Compute the FULL tax first, then split it into CGST + SGST so their sum
        # equals the full tax — i.e. the *same* amount an inter-state supply of the
        # same taxable value and rate would attract as IGST. Splitting the rate
        # first and flooring each half independently (the previous approach) lost
        # up to 1 paise for odd tax amounts (e.g. 0.25%/0.10% rates, or any taxable
        # whose full tax is odd), understating the GST liability and leaving
        # CGST+SGST ≠ IGST-equivalent. SGST carries any odd paise. Journal stays
        # balanced because total_paise is derived from these components.
        full_gst_paise = (taxable_paise * gst_rate_bps) // 10000
        cgst_paise = full_gst_paise // 2
        sgst_paise = full_gst_paise - cgst_paise
        return cgst_paise, sgst_paise, 0


def _round_off_paise(amount_paise: int) -> int:
    """Invoice-level round-off delta (integer paise) to the nearest rupee, half-up.

    Returns the adjustment to ADD to ``amount_paise`` so the payable total becomes
    a whole rupee: negative when rounding down (remainder < 50), positive when
    rounding up (remainder >= 50), and 0 when already whole. Range: [-49, +50].

    Commercial round-off (nearest ₹1). It is posted to the 'Round Off' ledger so
    the general ledger stays balanced. CGST Act §15: the value of supply and the
    GST thereon are NOT changed — round-off adjusts only the invoice total, and
    the tax heads (CGST/SGST/IGST) remain exactly as computed at source.
    """
    remainder = amount_paise % 100
    if remainder == 0:
        return 0
    if remainder < 50:
        return -remainder
    return 100 - remainder


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
                (inv.get("total_paise", 0) + (inv.get("debit_note_paise", 0) or 0)
                 - inv.get("paid_paise", 0) - (inv.get("credited_paise", 0) or 0))
                for inv in MOCK_SALES_INVOICES
                if inv["client_id"] == client_id and inv.get("status") not in ("paid", "cancelled")
            )
            return api_response(True, {"client_id": client_id, "outstanding_paise": total})

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = (
            db.table("client_sales_invoices")
            .select("total_paise,paid_paise,credited_paise,debit_note_paise")
            .eq("client_id", client_id)
            .eq("firm_id", current_user.get("firm_id"))
            .not_.in_("status", ["paid", "cancelled"])
            .execute()
        )
        # Net receivable = (total + debit notes) − cash paid − credit notes applied
        # (CGST Act §34, integer paise).
        outstanding = sum(
            (r.get("total_paise", 0) + (r.get("debit_note_paise", 0) or 0)
             - r.get("paid_paise", 0) - (r.get("credited_paise", 0) or 0))
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
        # Tenant isolation: service-role bypasses RLS, so firm_id is the only guard
        # against a cross-tenant read via a guessed client_id (H15).
        q = (db.table("client_sales_invoices").select("*")
             .eq("firm_id", current_user.get("firm_id")).eq("client_id", client_id))
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

        # Batch-fetch lines for the whole page in ONE query (was N+1 — audit H19):
        # 51 queries per 50-row page → 2. Group in Python.
        inv_ids = [inv["id"] for inv in invoices]
        lines_by_inv: dict[str, list] = {}
        if inv_ids:
            lr = (db.table("client_sales_invoice_lines").select("*")
                  .in_("sales_invoice_id", inv_ids).execute().data) or []
            for l in lr:
                lines_by_inv.setdefault(l.get("sales_invoice_id"), []).append(l)
        for inv in invoices:
            inv["lines"] = lines_by_inv.get(inv["id"], [])

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


def _apply_due_date_credit_days(data: dict, base_invoice_date: Optional[str]) -> None:
    """Mirror of _apply_credit_days_due_date: when due_date is set directly without
    an explicit credit_days (e.g. the post-issue Edit Details modal), recompute and
    re-store credit_days as the actual day-gap, so the derived "Terms" label
    (lib/sales/paymentTerms.ts) never goes stale relative to the real due date.
    No-op otherwise."""
    if not data.get("due_date") or data.get("credit_days") is not None:
        return
    if not base_invoice_date:
        return
    try:
        data["credit_days"] = (
            date.fromisoformat(str(data["due_date"])[:10])
            - date.fromisoformat(str(base_invoice_date)[:10])
        ).days
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
        invoice = _create_invoice_core(data.model_dump(), current_user)
        return api_response(True, invoice)
    except HTTPException:
        raise
    except Exception as e:
        # Full exception + traceback go to server logs only; client sees a generic message.
        _logger.error("create_invoice failed: %s", e, exc_info=True)
        return api_response(False, None, "Unable to create invoice. Please try again.")


def _create_invoice_core(data: dict, current_user: dict, bulk_cache: Optional[dict] = None) -> dict:
    """Shared invoice-creation logic used by both create_invoice and the bulk
    import endpoint below — extracted verbatim (no behavior change for a
    single create: bulk_cache is always None there) so the CSV importer can
    create many invoices in ONE request instead of firing one POST per
    invoice. Raises HTTPException on failure; returns the created invoice
    dict (with lines) on success.

    bulk_cache (bulk import only — see bulk_create_invoices, which pre-fetches
    it once per request instead of once per invoice):
      "customer": this invoice's customer row (already resolved by the caller)
      "client_rec": the selling client's row (shared across the whole batch)
      "existing_invoice_nos": mutable set of invoice_nos already taken for
        this client — checked and updated here instead of a per-invoice query,
        which also catches an intra-batch duplicate the CSV mapper missed.
    Skips the per-invoice HSN-preference/audit/timeline writes in bulk mode —
    all three are documented non-fatal, best-effort UX/audit metadata (never
    read by GST/journal/report code); bulk_create_invoices writes one summary
    audit + timeline entry for the whole batch afterward instead."""
    lines_data = data.get("lines", [])
    if not lines_data:
        raise HTTPException(status_code=422, detail="At least one line item is required")

    firm_id    = current_user.get("firm_id")
    client_id  = data["client_id"]
    invoice_no = data["invoice_no"]  # shape already validated by SalesInvoiceIn
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

        if bulk_cache is not None:
            customer = bulk_cache["customer"]
            client_rec = bulk_cache["client_rec"]
        else:
            # Fetch customer state code (firm-scoped — never read another firm's master)
            cust_resp = (
                db.table("customers")
                .select("state_code, gstin, credit_days, is_active")
                .eq("id", data["customer_id"])
                .eq("firm_id", firm_id)
                .limit(1)
                .execute()
            )
            customer = cust_resp.data[0] if cust_resp.data else {}
            # Fetch client state code from GSTIN (firm-scoped)
            client_resp = (
                db.table("clients")
                .select("gstin")
                .eq("id", client_id)
                .eq("firm_id", firm_id)
                .limit(1)
                .execute()
            )
            client_rec = client_resp.data[0] if client_resp.data else {}
        # Business guard: never raise an invoice against a deactivated customer.
        if customer and customer.get("is_active") is False:
            raise HTTPException(status_code=422, detail="This customer is inactive. Reactivate the customer before invoicing.")
        client_state_code = _get_state_code_from_gstin(client_rec.get("gstin")) or ""

    if bulk_cache is not None:
        if invoice_no in bulk_cache["existing_invoice_nos"]:
            raise HTTPException(status_code=409, detail=f"Invoice number '{invoice_no}' already exists for this client.")
        bulk_cache["existing_invoice_nos"].add(invoice_no)
    else:
        _assert_invoice_no_available(None if _USE_MOCK else db, firm_id, client_id, invoice_no)  # type: ignore[possibly-undefined]

    # Effective place of supply
    effective_supply_state = supply_state_code or customer.get("state_code") or ""  # type: ignore[possibly-undefined]

    if not _USE_MOCK:
        # CGST Act §8: Intra-state if both in same state; inter-state otherwise
        # (In mock mode is_interstate was already determined above from request flags)
        is_interstate = bool(client_state_code and effective_supply_state and client_state_code != effective_supply_state)

    # ── Multi-Currency (Phase 3): resolve + freeze the document currency ──────
    # INR / feature-off → identity (behaviour unchanged). For a foreign currency
    # this validates policy + master + rate and freezes the booking rate; the
    # line rate_paise below are then that currency's minor units.
    from domain.currency.document_currency import resolve_document_currency, identity_currency
    req_ccy = (data.get("currency") or "INR").strip().upper()
    if _USE_MOCK or req_ccy == "INR":
        dc = identity_currency(data["invoice_date"])
    else:
        _firm_row = (db.table("firms").select("multi_currency_entitled").eq("id", firm_id).limit(1).execute().data or [None])[0]
        _client_mc = (db.table("clients").select("functional_currency, multi_currency_enabled").eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0]
        dc = resolve_document_currency(
            db, _firm_row, _client_mc, currency=req_ccy,
            exchange_rate=data.get("exchange_rate"), rate_date=data["invoice_date"],
            rate_selected_by=current_user.get("id"))

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
            # `.get(k, default)` only falls back when the key is ABSENT, but
            # InvoiceLineIn.model_dump() always includes "unit" (as None when
            # the caller omits it) — so `or "NOS"` is required to catch both
            # "missing" and "explicitly None/blank".
            "unit":           ln.get("unit") or "NOS",
            "rate_paise":     rate_paise,
            "gst_rate_bps":   gst_rate_bps,
            "taxable_amount_paise": taxable_paise,
            "cgst_paise":     cgst_paise,
            "sgst_paise":     sgst_paise,
            "igst_paise":     igst_paise,
            "line_total_paise": taxable_paise + cgst_paise + sgst_paise + igst_paise,
            # Pure traceability (migration 184) — see InvoiceLineIn.service_catalogue_id.
            "service_catalogue_id": ln.get("service_catalogue_id"),
        })

    # The line totals above are in the document (txn) currency's minor units.
    # Convert each component to base (INR) paise at the frozen rate and define the
    # base TOTAL as their SUM, so the GL balances exactly with no FX-rounding
    # account. For INR, dc is the identity ⇒ base == txn and nothing changes.
    txn_taxable   = total_taxable_paise
    txn_total_gst = total_cgst_paise + total_sgst_paise + total_igst_paise
    txn_total     = txn_taxable + txn_total_gst
    base_taxable  = dc.to_base(total_taxable_paise)
    base_cgst     = dc.to_base(total_cgst_paise)
    base_sgst     = dc.to_base(total_sgst_paise)
    base_igst     = dc.to_base(total_igst_paise)
    base_total_gst = base_cgst + base_sgst + base_igst
    base_total     = base_taxable + base_total_gst
    # Invoice-level round-off (nearest ₹1) — INR invoices only. Absorbs the
    # sub-rupee GST remainder so the payable total is a clean rupee; the delta
    # is posted to the 'Round Off' ledger by journal_for_sales_invoice so the
    # journal stays balanced. Foreign-currency invoices are not rupee-rounded.
    round_off_paise = _round_off_paise(base_total) if dc.currency == "INR" else 0
    # Base is authoritative for the header/GL/reports; the *_paise names below now
    # carry base INR. (For INR these equal the txn values — byte-for-byte.)
    total_taxable_paise = base_taxable
    total_cgst_paise    = base_cgst
    total_sgst_paise    = base_sgst
    total_igst_paise    = base_igst
    total_paise         = base_total + round_off_paise

    # Currency columns written to the invoice (INR identity leaves them inert).
    _ccy_cols = {
        "txn_currency":     dc.currency,
        "exchange_rate":    str(dc.rate),
        "txn_taxable":      txn_taxable,
        "txn_total_gst":    txn_total_gst,
        # For INR, dc is identity so txn == base; keep txn_total consistent with
        # the rounded base total. round_off_paise is 0 for foreign currency.
        "txn_total":        txn_total + round_off_paise,
        "rate_source":      dc.rate_source,
        "rate_type":        dc.rate_type,
        "rate_date":        dc.rate_date,
        "rate_selected_by": dc.rate_selected_by,
        "rate_overridden":  dc.rate_overridden,
    }

    # Snapshot credit terms onto the invoice. The customer's credit_days is the
    # DEFAULT; an explicit due_date or credit_days on the request overrides it.
    # Storing the resolved values here means later edits to the customer's
    # Credit Days never change this (or any existing) invoice.
    eff_due_date, eff_credit_days = _resolve_credit_terms(
        data["invoice_date"], data.get("due_date"), data.get("credit_days"),
        customer.get("credit_days"),
    )

    # Validate posting date is not in a locked financial year (migration 020).
    # Memoized per FY within a bulk batch (bulk_cache carries the cache dict)
    # — see validate_posting_date_cached's docstring.
    period_validation_service.validate_posting_date_cached(
        firm_id or "", data["invoice_date"],
        bulk_cache.get("locked_fy_cache") if bulk_cache is not None else None,
    )

    if _USE_MOCK:
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
            "reference_no":          data.get("reference_no"),
            "taxable_amount_paise":  total_taxable_paise,
            "cgst_paise":            total_cgst_paise,
            "sgst_paise":            total_sgst_paise,
            "igst_paise":            total_igst_paise,
            "total_paise":           total_paise,
            "total_gst_paise":       total_cgst_paise + total_sgst_paise + total_igst_paise,
            "round_off_paise":       round_off_paise,
            "paid_paise":            0,
            "status":                "draft",
            "notes":                 data.get("notes", ""),
            "created_by":            current_user.get("auth_user_id"),
            "created_at":            datetime.now(timezone.utc).isoformat(),
            **_ccy_cols,
            "lines":                 computed_lines,
        }
        MOCK_SALES_INVOICES.append(invoice)
        for ln in computed_lines:
            ln["id"] = str(uuid.uuid4())
            ln["invoice_id"] = invoice_id
            MOCK_SALES_INVOICE_LINES.append(ln)
        return invoice

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
        "reference_no":          data.get("reference_no"),
        "taxable_amount_paise":  total_taxable_paise,
        "cgst_paise":            total_cgst_paise,
        "sgst_paise":            total_sgst_paise,
        "igst_paise":            total_igst_paise,
        "total_paise":           total_paise,
        "total_gst_paise":       total_cgst_paise + total_sgst_paise + total_igst_paise,
        "round_off_paise":       round_off_paise,
        "paid_paise":            0,
        "status":                "draft",
        "notes":                 data.get("notes", ""),
        "created_by":            current_user.get("auth_user_id"),
        "created_at":            datetime.now(timezone.utc).isoformat(),
        **_ccy_cols,
    }

    # invoice_no is manual (CA-typed) and already duplicate-checked above;
    # the UNIQUE(firm_id, client_id, invoice_no) constraint (migration 151)
    # is still the final backstop for a genuine concurrent race — translate
    # that into the same friendly message rather than a raw 500. Unlike
    # auto-generated document numbers (services.numbering.insert_with_number),
    # retrying with a DIFFERENT number would silently override what the CA typed.
    from services.numbering import is_unique_violation
    try:
        ins_resp = db.table("client_sales_invoices").insert(invoice_payload).execute()
        invoice = (ins_resp.data or [invoice_payload])[0]
    except HTTPException:
        raise
    except Exception as e:
        if is_unique_violation(e):
            raise HTTPException(status_code=409, detail=f"Invoice number '{invoice_no}' already exists for this client.")
        raise
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
            "service_catalogue_id":  ln["service_catalogue_id"],
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

    # Per-invoice HSN-preference/audit/timeline writes — skipped in bulk mode
    # (see the bulk_cache docstring above): bulk_create_invoices writes one
    # summary audit + timeline entry for the whole batch instead of firm_id/
    # client_id-identical rows repeated once per imported invoice.
    if bulk_cache is None:
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
    return invoice


class _BulkInvoicesIn(BaseModel):
    invoices: list[dict]


@router.post("/bulk")
def bulk_create_invoices(
    payload: _BulkInvoicesIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Create many sales invoices in ONE request.

    The CSV importer used to fire one POST /api/sales-invoices/ per invoice —
    for a 100-row import that's 100 sequential network round-trips, and it
    multiplies badly when many firms import concurrently. This endpoint loops
    the exact same _create_invoice_core logic server-side, so N round-trips
    collapse to roughly 1 for the WHOLE batch: the customer/client rows and
    the set of already-used invoice numbers are pre-fetched ONCE here
    (bulk_cache) instead of once per invoice inside _create_invoice_core —
    at a few thousand rows, that per-invoice version is the difference
    between a few seconds and tens of minutes (almost certainly past any
    request timeout, and with no way to tell how much of the batch actually
    landed if it does). A bad row is reported per-item and does not abort the
    rest of the batch — matches the existing CSV-import UX (partial success
    with a per-row error list).
    """
    items = payload.invoices
    created: list[dict] = []
    errors: list[dict] = []
    firm_id = current_user.get("firm_id")

    # Parse/validate every row up front so the pre-fetch below only has to
    # cover rows that will actually reach _create_invoice_core.
    parsed: list[tuple[int, str, SalesInvoiceIn]] = []
    for i, raw in enumerate(items):
        invoice_no = raw.get("invoice_no", "") if isinstance(raw, dict) else ""
        try:
            parsed.append((i, invoice_no, SalesInvoiceIn(**raw)))
        except PydanticValidationError as e:
            errors.append({"index": i, "invoice_no": invoice_no, "error": str(e.errors()[0].get("msg", "Invalid invoice data")) if e.errors() else "Invalid invoice data"})

    customers_by_id: dict = {}
    clients_by_id: dict = {}
    # client_id -> set(invoice_no already taken) — scoped per client to match
    # the real UNIQUE(firm_id, client_id, invoice_no) constraint (migration
    # 151); shared/mutated across the loop below so an intra-batch duplicate
    # (two rows with the same invoice_no the CSV mapper somehow let through)
    # is caught the same way a pre-existing one is.
    existing_invoice_nos_by_client: dict = {}
    if parsed and not _USE_MOCK:
        from core.supabase_client import get_supabase
        db = get_supabase()
        client_ids = list({p[2].client_id for p in parsed})
        customer_ids = list({p[2].customer_id for p in parsed})
        CHUNK = 200  # stay well under any PostgREST IN-list/URL-length limit
        for i in range(0, len(customer_ids), CHUNK):
            chunk = customer_ids[i:i + CHUNK]
            resp = (db.table("customers").select("id, state_code, gstin, credit_days, is_active")
                    .eq("firm_id", firm_id).in_("id", chunk).execute())
            for r in (resp.data or []):
                customers_by_id[r["id"]] = r
        for i in range(0, len(client_ids), CHUNK):
            chunk = client_ids[i:i + CHUNK]
            resp = db.table("clients").select("id, gstin").eq("firm_id", firm_id).in_("id", chunk).execute()
            for r in (resp.data or []):
                clients_by_id[r["id"]] = r
        for cid in client_ids:
            # deleted_at filter — same reasoning as _assert_invoice_no_available:
            # a deleted invoice's number is free to reuse, including via import.
            resp = (db.table("client_sales_invoices").select("invoice_no")
                    .eq("firm_id", firm_id).eq("client_id", cid).is_("deleted_at", "null").execute())
            existing_invoice_nos_by_client[cid] = {r["invoice_no"] for r in (resp.data or [])}
    elif parsed and _USE_MOCK:
        for cid in {p[2].client_id for p in parsed}:
            existing_invoice_nos_by_client[cid] = {
                inv.get("invoice_no") for inv in MOCK_SALES_INVOICES
                if inv.get("firm_id") == firm_id and inv.get("client_id") == cid and not inv.get("deleted_at")
            }

    # Locked-FY status is firm-wide and cannot change mid-request — shared and
    # mutated across the whole loop (see validate_posting_date_cached) so a
    # batch spanning 2 financial years costs 2 RPC calls, not one per invoice.
    locked_fy_cache: dict = {}

    for i, invoice_no, data in parsed:
        try:
            bulk_cache = {
                "customer": customers_by_id.get(data.customer_id, {}),
                "client_rec": clients_by_id.get(data.client_id, {}),
                "existing_invoice_nos": existing_invoice_nos_by_client.setdefault(data.client_id, set()),
                "locked_fy_cache": locked_fy_cache,
            }
            invoice = _create_invoice_core(data.model_dump(), current_user, bulk_cache=bulk_cache)
            created.append(invoice)
        except HTTPException as e:
            errors.append({"index": i, "invoice_no": invoice_no, "error": e.detail})
        except Exception as e:
            _logger.error("bulk_create_invoices item %d failed: %s", i, e, exc_info=True)
            errors.append({"index": i, "invoice_no": invoice_no, "error": "Unable to create this invoice. Please try again."})

    # One summary audit + timeline entry for the whole batch instead of one
    # per invoice (skipped inside _create_invoice_core for bulk_cache calls
    # — see its docstring): a bulk import's real audit-trail question is
    # "who imported N invoices and when", not N near-identical entries.
    if created:
        log_event(
            firm_id, "sales_invoice", "bulk_import", "create",
            actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
            new_data={"count": len(created), "invoice_nos": [c.get("invoice_no") for c in created][:100]},
        )
        by_client: dict[str, list[dict]] = {}
        for c in created:
            by_client.setdefault(c.get("client_id", ""), []).append(c)
        for cid, invs in by_client.items():
            if not cid:
                continue
            total = sum(inv.get("total_paise", 0) for inv in invs)
            timeline_service.log(
                cid, "accounting", "Sales Invoices Imported",
                f"{len(invs)} invoice(s) imported via bulk upload, totaling ₹{total // 100:,}.",
                "info", firm_id=firm_id or "",
                entity_type="sales_invoice", amount_paise=total,
                actor_id=current_user.get("auth_user_id"),
            )
    return api_response(True, {"created": created, "errors": errors})


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


# Once an invoice is issued, only these fields may still change — none of
# them affect amount or tax, so a correction doesn't need a Credit Note.
# (line_units is handled separately below; it's popped out of `data` before
# this set is checked, since it's always allowed regardless of status.)
_SOFT_UPDATE_FIELDS = {"reference_no", "notes", "due_date", "credit_days"}


def _reject_locked_invoice_fields(data: dict) -> None:
    """Everything outside _SOFT_UPDATE_FIELDS is CGST Rule 46 tax-invoice
    content (invoice_no, dates, customer, line qty/rate/HSN/GST,
    is_interstate) — CGST Act §34 requires a Credit Note to correct any of
    that once issued, never a silent edit."""
    locked = sorted(set(data.keys()) - _SOFT_UPDATE_FIELDS)
    if locked:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot change {', '.join(locked)} on an issued invoice — only "
                "reference/PO number, notes and due date can still be edited. "
                "Issue a Credit Note to correct anything else (CGST Act §34)."
            ),
        )


@router.patch("/{invoice_id}")
def update_invoice(
    invoice_id: str,
    data: SalesInvoiceUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Update an invoice. DRAFT: full edit, recomputes GST if lines change.
    ISSUED/PARTIALLY_PAID/PAID: only reference_no, notes, due_date/
    credit_days and per-line unit (line_units) may change — see
    _reject_locked_invoice_fields. CANCELLED: cannot be updated at all."""
    try:
        data = data.model_dump(exclude_none=True)
        # The request model field is is_inter_state; the DB column is is_interstate.
        # Map it so the flag (the form's IGST checkbox) both drives the GST recompute
        # below and persists correctly — without this the column write would 400.
        if "is_inter_state" in data:
            data["is_interstate"] = data.pop("is_inter_state")
        # Always allowed regardless of status — unit alone never touches
        # rate/quantity/amount/GST, unlike a full `lines` replace.
        line_units = data.pop("line_units", None)

        if _USE_MOCK:
            for i, inv in enumerate(MOCK_SALES_INVOICES):
                if inv["id"] == invoice_id:
                    status = inv.get("status")
                    if status == "cancelled":
                        raise HTTPException(status_code=422, detail="Cancelled invoices cannot be updated")
                    if status != "draft":
                        _reject_locked_invoice_fields(data)
                    if "invoice_no" in data:
                        _assert_invoice_no_available(
                            None, current_user.get("firm_id"), inv.get("client_id"),
                            data["invoice_no"], exclude_id=invoice_id,
                        )
                    _apply_credit_days_due_date(data, data.get("invoice_date") or inv.get("invoice_date"))
                    _apply_due_date_credit_days(data, data.get("invoice_date") or inv.get("invoice_date"))
                    if line_units:
                        for ln in MOCK_SALES_INVOICE_LINES:
                            if ln.get("id") in line_units and ln.get("invoice_id") == invoice_id:
                                ln["unit"] = line_units[ln["id"]] or "NOS"
                    MOCK_SALES_INVOICES[i] = {**inv, **data, "updated_at": datetime.now(timezone.utc).isoformat()}
                    return api_response(True, MOCK_SALES_INVOICES[i])
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        firm_id = current_user.get("firm_id") or ""

        # Check current status
        resp = db.table("client_sales_invoices").select("status, invoice_date, client_id").eq("id", invoice_id).eq("firm_id", firm_id).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        status = resp.data[0]["status"]
        if status == "cancelled":
            raise HTTPException(status_code=422, detail="Cancelled invoices cannot be updated")
        if status != "draft":
            _reject_locked_invoice_fields(data)
        if "invoice_no" in data:
            _assert_invoice_no_available(
                db, firm_id, resp.data[0]["client_id"], data["invoice_no"], exclude_id=invoice_id,
            )
        # FY-lock: block editing an invoice dated in a locked year, and block moving
        # it INTO a locked year. (Create already validates; edits were the gap.)
        existing_date = resp.data[0].get("invoice_date")
        if existing_date:
            period_validation_service.validate_posting_date(firm_id, existing_date)
        if data.get("invoice_date"):
            period_validation_service.validate_posting_date(firm_id, data["invoice_date"])

        # Keep due_date and credit_days in sync whichever one was edited directly
        # (credit_days -> due_date, or due_date -> credit_days), so the derived
        # "Terms" label never goes stale relative to the actual due date. Snapshot
        # stays on the invoice only.
        if data.get("credit_days") is not None or data.get("due_date"):
            base_date = data.get("invoice_date")
            if not base_date:
                d2 = (db.table("client_sales_invoices").select("invoice_date")
                      .eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute())
                base_date = d2.data[0].get("invoice_date") if d2.data else None
            _apply_credit_days_due_date(data, base_date)
            _apply_due_date_credit_days(data, base_date)

        # If lines are provided, recompute GST
        if "lines" in data:
            # Fetch current invoice for the is_interstate flag. An edit may change
            # it (the IGST checkbox) — honour the new value, else keep the stored
            # one. The GST math (_compute_line_gst) itself is unchanged.
            inv_resp = db.table("client_sales_invoices").select("*").eq("id", invoice_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
            inv = inv_resp.data[0]
            is_interstate = data.get("is_interstate", inv.get("is_interstate", False))
            # task #103: currency/exchange_rate can never change on edit (no such
            # fields on SalesInvoiceUpdateIn) — reconstruct the FROZEN DocumentCurrency
            # from the already-stored row (never re-resolve/re-validate a new rate).
            from domain.currency.document_currency import document_currency_from_row
            dc = document_currency_from_row(db, inv)

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
                    # See the analogous comment in create_invoice: model_dump()
                    # always includes "unit" (None when omitted), so `.get(k,
                    # default)` alone wouldn't fall back — `or "NOS"` is required.
                    "unit":                 ln.get("unit") or "NOS",
                    "rate_paise":           rate_paise,
                    "gst_rate_bps":         gst_rate_bps,
                    "taxable_amount_paise": taxable,
                    "cgst_paise":           cgst,
                    "sgst_paise":           sgst,
                    "igst_paise":           igst,
                    "line_total_paise":     taxable + cgst + sgst + igst,
                    # Pure traceability (migration 184) — see InvoiceLineIn.service_catalogue_id.
                    # Must be carried through here too: this is a delete-then-
                    # reinsert, so any line the frontend re-sends without it
                    # would silently drop the link on save, wrongly making an
                    # in-use preset look deletable again.
                    "service_catalogue_id": ln.get("service_catalogue_id"),
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
            # task #103: the per-line totals above are in the document's TXN currency
            # minor units (same as _create_invoice_core's pre-conversion sums) — they
            # must be converted to base (INR) paise via dc.to_base before being written
            # to the base *_paise columns, exactly like create does (and like
            # update_purchase_bill already does via _compute_bill_lines_and_totals).
            # Previously this wrote the raw txn-currency sums straight into the base
            # columns (a $1,000 line at rate 83.5 wrote ₹1,000, not ₹83,500 — a ~83x
            # understatement) and never refreshed txn_taxable/txn_total_gst/txn_total,
            # leaving them stale from creation.
            txn_taxable    = total_taxable
            txn_total_gst  = total_cgst + total_sgst + total_igst
            txn_total      = txn_taxable + txn_total_gst
            base_taxable   = dc.to_base(total_taxable)
            base_cgst      = dc.to_base(total_cgst)
            base_sgst      = dc.to_base(total_sgst)
            base_igst      = dc.to_base(total_igst)
            base_total_gst = base_cgst + base_sgst + base_igst
            base_total     = base_taxable + base_total_gst
            # Invoice-level round-off (nearest ₹1), mirroring the create path. INR
            # only — a foreign-currency draft (dc.currency != INR) is not rounded.
            round_off_edit = _round_off_paise(base_total) if dc.currency == "INR" else 0
            data["taxable_amount_paise"] = base_taxable
            data["cgst_paise"]           = base_cgst
            data["sgst_paise"]           = base_sgst
            data["igst_paise"]           = base_igst
            data["total_gst_paise"]      = base_total_gst
            data["round_off_paise"]      = round_off_edit
            data["total_paise"]          = base_total + round_off_edit
            data["txn_taxable"]          = txn_taxable
            data["txn_total_gst"]        = txn_total_gst
            data["txn_total"]            = txn_total + round_off_edit

        # Per-line unit correction — independent of the full lines-replace
        # block above (draft-only), safe on any non-cancelled status since
        # unit never affects rate/quantity/amount/GST.
        if line_units:
            for line_id, unit in line_units.items():
                db.table("client_sales_invoice_lines").update(
                    {"unit": unit or "NOS"}
                ).eq("id", line_id).eq("sales_invoice_id", invoice_id).execute()

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
        # FY-lock: issuing posts a dated journal — block if the year was locked after
        # the draft was created (deferred-posting gap).
        if inv.get("invoice_date"):
            period_validation_service.validate_posting_date(current_user.get("firm_id") or "", inv["invoice_date"])

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

        # Inventory: stock-out + COGS journal for any goods lines linked to a
        # stock-tracked catalogue item. Runs AFTER the invoice is committed
        # issued above — a failure here (e.g. Inventory/COGS control accounts
        # not set up yet) must never affect an already-issued invoice.
        # apply_sale_to_inventory itself never raises; this try/except is
        # belt-and-suspenders.
        try:
            from domain.inventory_service import apply_sale_to_inventory
            apply_sale_to_inventory(
                db, firm_id=current_user.get("firm_id", ""), client_id=updated_inv.get("client_id", ""),
                # journal_entries.created_by FK references users(id), not the
                # auth_user_id (JWT sub / auth.users.id) — see
                # phase2_journal_service.reverse_entry's created_by a few
                # lines above, which already gets this right.
                invoice=updated_inv, created_by=current_user.get("id"),
            )
        except Exception as e:
            _logger.error("issue_invoice: inventory posting failed for %s: %s", invoice_id, e, exc_info=True)

        updated_inv["journal_entry_id"] = journal_id
        return api_response(True, updated_inv)
    except HTTPException:
        raise
    except Exception as e:
        # journal_for_sales_invoice now re-raises unexpected errors (Batch 1) — log
        # the full traceback so an operator can diagnose, while the CA sees a safe
        # generic message and the invoice remains a re-tryable draft (nothing posted).
        _logger.error("issue_invoice: %s", e, exc_info=True)
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
        from services.phase2_journal_service import phase2_journal_service
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        resp = (db.table("client_sales_invoices")
                .select("status, journal_entry_id, invoice_no, client_id, paid_paise, credited_paise, debit_note_paise")
                .eq("id", invoice_id).eq("firm_id", firm_id).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Invoice {invoice_id} not found")
        inv = resp.data[0]
        status = inv.get("status")
        if status == "cancelled":
            raise HTTPException(status_code=422, detail="Invoice already cancelled")
        if status == "draft":
            raise HTTPException(status_code=422, detail="Draft invoices are deleted, not cancelled.")
        # Accounting guard (prevent cancellation where the rules require): never cancel
        # an invoice that carries settlements — the receipt/credit-note/debit-note
        # journals would be stranded (a debit note's allocation would orphan too).
        # Reverse those or issue a credit/debit note instead (CGST Act §34).
        if (int(inv.get("paid_paise") or 0) > 0 or int(inv.get("credited_paise") or 0) > 0
                or int(inv.get("debit_note_paise") or 0) > 0):
            raise HTTPException(
                status_code=409,
                detail=("This invoice has receipts, credit notes or debit notes applied and cannot be cancelled. "
                        "Reverse the receipt(s) or issue a credit/debit note instead."),
            )

        # A cancellation reversal is a NEW posting dated today — it must fall in an
        # open financial year.
        reversal_date = datetime.now(timezone.utc).date().isoformat()
        period_validation_service.validate_posting_date(firm_id or "", reversal_date)

        # Locate the invoice's posted issue-journal and reverse it THROUGH the kernel
        # (append-only; the original entry is never modified). Idempotent: if a prior
        # attempt already posted the reversal, skip straight to the status flip.
        jrnl_id = inv.get("journal_entry_id")
        if not jrnl_id:
            # entry_type filter matters: without it, ANY posted journal whose
            # reference matched the invoice number could be picked — e.g. a
            # purchase journal from a vendor bill numbered the same — and this
            # cancellation would reverse the WRONG document's journal. The
            # purchase-bill cancel path already filtered entry_type; this was
            # the one asymmetric lookup.
            jr = (db.table("journal_entries").select("id")
                  .eq("firm_id", firm_id).eq("client_id", inv.get("client_id"))
                  .eq("reference_no", inv.get("invoice_no")).eq("entry_type", "Sales").eq("is_posted", True)
                  .limit(1).execute().data)
            jrnl_id = jr[0]["id"] if jr else None
        if not jrnl_id:
            raise HTTPException(status_code=422, detail="No posted journal found for this invoice to reverse.")
        already = (db.table("journal_entries").select("id")
                   .eq("firm_id", firm_id).eq("reversal_of", jrnl_id).limit(1).execute().data)
        if not already:
            phase2_journal_service.reverse_entry(
                db, firm_id, jrnl_id, reversal_date,
                narration=f"Cancellation of invoice {inv.get('invoice_no') or invoice_id}",
                created_by=current_user.get("id"),
            )

        upd = db.table("client_sales_invoices").update({
            "status":       "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", invoice_id).eq("firm_id", firm_id).execute()

        updated = upd.data[0] if upd.data else {}

        # Inventory: undo the stock-out + COGS journal apply_sale_to_inventory
        # posted at issue time, for any goods lines on this invoice. Runs
        # AFTER cancellation is committed — never blocks it.
        try:
            from domain.inventory_service import reverse_sale_stock
            reverse_sale_stock(
                db, firm_id=firm_id or "", client_id=inv.get("client_id", ""), invoice_id=invoice_id,
                # journal_entries.created_by FK references users(id), not auth_user_id.
                invoice_no=inv.get("invoice_no", ""), created_by=current_user.get("id"),
            )
        except Exception as e:
            _logger.error("cancel_invoice: inventory reversal failed for %s: %s", invoice_id, e, exc_info=True)

        log_event(
            firm_id or "", "sales_invoice", invoice_id,
            "cancel", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"status": "cancelled", "reversed_journal": jrnl_id},
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

        # H3: reposting writes a dated journal — it must respect the FY lock exactly
        # like issue_invoice does (this path previously skipped the check).
        if inv.get("invoice_date"):
            period_validation_service.validate_posting_date(firm_id or "", inv["invoice_date"])

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
