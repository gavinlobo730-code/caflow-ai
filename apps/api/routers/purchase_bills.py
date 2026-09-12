"""Purchase bills — vendor bills with GST computation and TDS auto-deduction.
IT Act Section 194C: TDS on contractor payments.
IT Act Section 194I: TDS on rent.
IT Act Section 194J: TDS on professional/technical fees.
# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
"""
import os
import uuid
import logging
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ValidationError as PydanticValidationError
from dataclasses import asdict
from domain.purchases import near_duplicate
from models.common import api_response
from models.invoices import PurchaseBillIn, PurchaseBillUpdateIn, BillFromDocumentIn
from core.authz import assert_client_access
from core.observability import capture_soft_failure
from core.exceptions import document_failure_detail
from core.permissions import rbac
from services.audit_service import log_event
from services.credit_terms import resolve_credit_terms, apply_credit_days_due_date, apply_due_date_credit_days
from services.period_validation_service import period_validation_service
from services import period_lock_service
from services import vendor_tds
from services.timeline_service import timeline_service
from core.ist_clock import ist_fy_label

# _TDS_DEFAULT_BPS WAS HERE AND IS DELETED. It mapped six sections to flat
# rates and had no readers — grep proved it dead — but it was the last place in
# apps/api asserting a rate for §194IA, and it was demonstrably a Finance Act
# behind: it gave §194H 500 bps where domain/tds/section_rates.py records the
# Finance (No. 2) Act 2024 cut to 200. Left in place it is a plausible-looking
# source for exactly the numbers Phase 4 refuses to guess at.
#
# There is one rate table and it is domain/tds/section_rates.py, which carries
# per-payee-type rates, thresholds, aggregate limbs and a verified flag per FY.
# A flat map cannot express any of those.

_USE_MOCK = not os.environ.get("SUPABASE_URL")
_logger = logging.getLogger("caflow.purchase_bills")


# ── Client-assignment scope (M2) ───────────────────────────────────────────────
# `core.authz` makes only the **Partner** firm-wide (`_FIRMWIDE_ROLES`); a
# Manager, Executive or Reviewer sees only the clients in
# `user_client_assignments`. This router enforced none of it — it did not import
# core.authz at all — so `GET /?client_id=…` listed any client's payables to any
# member of the firm, `POST /` created a bill in any client's books, and the
# `/{bill_id}` endpoints accepted an id from any client, `/receive` included,
# which posts the bill's journal and its input GST credit.
#
# Same two entry points as sales_invoices: a client named directly by a
# parameter, or named indirectly by a bill id that must be resolved first.

def _bill_owner(current_user: dict, bill_id: str) -> tuple[bool, Optional[str]]:
    """`(row_exists, client_id)` for this bill, firm-scoped.

    A pair rather than just the id because "no such bill" and "a bill whose
    client_id came back empty" are different answers and must not collapse into
    one. `purchase_bills.client_id` is NOT NULL (migration 050), so the second
    case means a projection that did not select the column, not a real orphan —
    and `assert_client_access(user, None)` reads that as a firm-level resource.

    Deliberately does NOT filter `deleted_at` — who owns a soft-deleted bill is
    still the right answer to "may this caller act on it"; whether the row is
    actionable stays each handler's own decision.
    """
    if _USE_MOCK:
        bill = next((b for b in MOCK_PURCHASE_BILLS if b.get("id") == bill_id), None)
        return (bill is not None, bill.get("client_id") if bill else None)
    from core.supabase_client import get_supabase
    rows = (get_supabase().table("purchase_bills").select("client_id")
            .eq("id", bill_id).eq("firm_id", current_user.get("firm_id"))
            .limit(1).execute().data) or []
    return (bool(rows), rows[0].get("client_id") if rows else None)


def _assert_bill_scope(current_user: dict, bill_id: str) -> Optional[str]:
    """404 unless the caller may act on this bill's client.

    404 rather than 403, and the same 404 as "no such bill" — otherwise the
    status code becomes an oracle for which bill ids are real.
    """
    found, client_id = _bill_owner(current_user, bill_id)
    if not found:
        # Mock mode: several handlers answer from a stub without touching
        # MOCK_PURCHASE_BILLS, so a missing row means "nothing to scope", not
        # "denied" — each handler still raises its own 404. Real enforcement
        # runs when SUPABASE_URL is set, the only mode with assignments.
        if _USE_MOCK:
            return None
        raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
    assert_client_access(current_user, client_id)
    return client_id


def _assert_batch_scope(current_user: dict, client_ids) -> None:
    """Every DISTINCT client in a bulk payload, checked before ANY row is written.

    Per-row checking would let the rows before the first refusal land, leaving a
    mixed batch half-applied — and a bulk endpoint is exactly where one foreign
    client_id would be slipped in among fifty legitimate ones.
    """
    for client_id in sorted({c for c in client_ids if c}):
        assert_client_access(current_user, client_id)




router = APIRouter(prefix="/api/purchase-bills", tags=["purchase_bills"])

# ---------------------------------------------------------------------------
# Mock stores
# ---------------------------------------------------------------------------
MOCK_PURCHASE_BILLS: list[dict] = []
MOCK_PURCHASE_BILL_LINES: list[dict] = []


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

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
    # Compute the FULL tax first, then split into CGST + SGST so their sum
    # equals what the same supply would attract as IGST — identical to the
    # sales-side fix in routers/sales_invoices.py. Splitting the rate first
    # and flooring each half independently lost up to 1 paise per line for
    # odd tax amounts, and was badly wrong for odd-bps rates (0.25% → 25 bps,
    # half=12 bps → ₹24 instead of ₹25 per ₹10,000), systematically
    # understating ITC on purchases. SGST carries any odd paise.
    full_gst = (taxable_paise * gst_rate_bps) // 10000
    cgst = full_gst // 2
    sgst = full_gst - cgst
    return cgst, sgst, 0


def _get_state_code_from_gstin(gstin: Optional[str]) -> Optional[str]:
    if gstin and len(gstin) >= 2:
        return gstin[:2]
    return None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.get("/")
def list_purchase_bills(
    client_id: str = Query(..., description="CA client ID — required"),
    vendor_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    from_date: Optional[str] = Query(None, description="Filter by bill_date >= from_date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Filter by bill_date <= to_date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """List purchase bills with optional filters."""
    assert_client_access(current_user, client_id)
    try:
        if _USE_MOCK:
            result = [b for b in MOCK_PURCHASE_BILLS if b["client_id"] == client_id and not b.get("deleted_at")]
            if vendor_id:
                result = [b for b in result if b.get("vendor_id") == vendor_id]
            if status:
                result = [b for b in result if b.get("status") == status]
            if from_date:
                result = [b for b in result if b.get("bill_date", "") >= from_date]
            if to_date:
                result = [b for b in result if b.get("bill_date", "") <= to_date]
            result = result[offset:offset + limit]
            return api_response(True, result)

        from core.supabase_client import get_supabase
        db = get_supabase()
        q = db.table("purchase_bills").select("*").eq("firm_id", current_user["firm_id"]).eq("client_id", client_id).is_("deleted_at", None)
        if vendor_id:
            q = q.eq("vendor_id", vendor_id)
        if status:
            q = q.eq("status", status)
        if from_date:
            q = q.gte("bill_date", from_date)
        if to_date:
            q = q.lte("bill_date", to_date)
        resp = q.order("bill_date", desc=True).range(offset, offset + limit - 1).execute()
        return api_response(True, resp.data or [])
    except Exception as e:
        _logger.error("list_purchase_bills: %s", e)
        return api_response(False, None, f"Unable to complete purchase bill operation: {e}")


@router.post("/")
def create_purchase_bill(
    data: PurchaseBillIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Create a purchase bill with automatic GST computation and TDS deduction.
    IT Act §194C/194I/194J: TDS rates sourced from vendor master.
    All monetary values in integer paise. Status: 'draft'.
    """
    assert_client_access(current_user, data.client_id)
    try:
        bill = _create_purchase_bill_core(data.model_dump(), current_user)
        return api_response(True, bill)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_purchase_bill: %s", e)
        capture_soft_failure(e, operation="create_purchase_bill")
        return api_response(False, None,
                            document_failure_detail(e, action="create the purchase bill"))


class NearDuplicateProbeIn(BaseModel):
    """What the bill form knows before it saves."""
    client_id: str
    vendor_id: str
    bill_no: Optional[str] = None
    bill_date: Optional[str] = None
    total_paise: int = 0


@router.post("/near-duplicates")
def probe_near_duplicates(
    data: NearDuplicateProbeIn,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Bills of this vendor the one being typed may be a second copy of.

    The same rule the create path applies, offered BEFORE the save so the CA
    can look at the other document while the form is still open. Read-only,
    and it never refuses anything: `domain/purchases/near_duplicate` carries
    the argument for warning rather than blocking.

    Deliberately a POST rather than a GET despite reading nothing: an invoice
    number is a document identifier that has no business in a URL, a query
    string or an access log, and the same reasoning already keeps
    `/tds-preview` a POST.
    """
    assert_client_access(current_user, data.client_id)
    if _USE_MOCK:
        # Nothing to compare against. An empty list would read as "checked and
        # clean", which is a stronger claim than mock mode can make.
        return api_response(True, {"checked": False, "near_duplicates": []})
    try:
        from core.supabase_client import get_supabase
        found = _near_duplicates(
            get_supabase(), data.client_id, data.vendor_id,
            bill_no=data.bill_no, bill_date=data.bill_date,
            total_paise=data.total_paise)
        return api_response(True, {"checked": True, "near_duplicates": found})
    except Exception as e:                                      # noqa: BLE001
        _logger.error("probe_near_duplicates: %s", e)
        return api_response(False, None, "Could not check for similar bills.")


@router.post("/tds-preview")
def preview_purchase_bill_tds(
    data: PurchaseBillIn,
    # A QUERY parameter rather than a body field: the body is the create
    # model, and the preview must take exactly what the save takes or the two
    # can drift on shape as well as on arithmetic. On an EDIT the bill already
    # exists carrying its own taxable amount, so it has to be excluded from its
    # own FY-prior aggregate — the same reason update_purchase_bill excludes it.
    exclude_bill_id: Optional[str] = Query(default=None),
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """What this bill will withhold, computed by the code that will withhold it.

    THE POINT IS THAT IT IS THE SAME CODE. The bill editor used to compute its
    own preview in the browser — `estimateForeignTds(base, vendor.tds_rate_bps)`,
    a bare rate x base with no threshold, no s.206AA floor, no FY aggregate and
    no s.195 branch — and then subtract it to show "Net payable". The server
    decides on RESIDENCY first: a non-resident goes through s.195 (rate by
    nature of income, plus surcharge and cess, and a REFUSAL where chargeability
    or a treaty position is unknown), a resident through resolve_tds with the
    section threshold, the year's aggregate and the s.206AA floor. None of those
    inputs exists in the browser (TDS-14).

    So a sub-threshold s.194J bill previewed tax and saved zero, and a
    non-resident bill previewed a resident rate and saved base + surcharge +
    cess, or 422'd. The CA approved one number and the ledger recorded another.

    Computes nothing of its own: same _resolve_vendor_and_interstate, same
    _compute_bill_lines_and_totals, same inputs as _create_purchase_bill_core.
    Writes nothing, and the 422 a refusal raises is the SAME refusal the save
    would raise — which is the useful half, because it arrives while the CA can
    still act on it.
    """
    assert_client_access(current_user, data.client_id)
    try:
        body = data.model_dump()
        firm_id = current_user.get("firm_id") or ""
        vendor, is_interstate, db = _resolve_vendor_and_interstate(
            firm_id, body["client_id"], body["vendor_id"])
        dc = _resolve_bill_currency(db, firm_id, body, current_user)
        computed = _compute_bill_lines_and_totals(
            body.get("lines") or [], is_interstate, vendor, body["bill_date"],
            firm_id, dc, db=db,
            # The bill being edited must not count itself in its own FY
            # aggregate — the same reason update_purchase_bill passes it.
            exclude_bill_id=exclude_bill_id,
            is_reverse_charge=bool(body.get("is_reverse_charge", False)),
        )
        return api_response(True, {
            "taxable_amount_paise": computed["taxable_amount_paise"],
            "total_paise":          computed["total_paise"],
            "total_gst_paise":      computed["total_gst_paise"],
            "tds_paise":            computed["tds_paise"],
            "tds_rate_bps":         computed["tds_rate_bps"],
            "tds_section":          computed["tds_section"],
            "tds_surcharge_paise":  computed["tds_surcharge_paise"],
            "tds_cess_paise":       computed["tds_cess_paise"],
            "tds_nature_of_income": computed["tds_nature_of_income"],
            # WHY that figure, in the engine's own words. A number with no
            # reason is a number a CA cannot check, and this one moves with the
            # year's running total: the same vendor and the same amount deduct
            # differently on the bill that crosses the threshold.
            # WHY that figure. On a s.195 bill it is the basis the engine
            # resolved on (not_chargeable / treaty / act / 206aa_floor); on a
            # resident bill it is the aggregate the charge fell on and what
            # earlier bills already withheld. Whichever exists.
            "tds_basis":            computed.get("_tds_resident_reason") or computed["tds_basis"],
            "tds_citation":         computed.get("_tds_citation"),
            # What the year's aggregate demanded and this bill was too small to
            # withhold. It is not lost — the next bill to the same payee
            # re-charges it — but the CA is told rather than left to infer it
            # from a net payable of nil. s.201(1A) runs at 1% a month until it
            # is deducted.
            "tds_shortfall_paise":  computed.get("_tds_shortfall_paise", 0),
            "net_payable_paise":    computed["net_payable_paise"],
            # The same figures in the bill's own currency, so a foreign bill's
            # "net payable" is not reconstructed in the browser from an INR
            # deduction and a rate — which is a second conversion, at a rate the
            # server has already frozen.
            "txn_currency":         dc.currency,
            "txn_total":            computed["txn_total"],
            "txn_net_payable":      computed["txn_net_payable"],
        })
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("preview_purchase_bill_tds: %s", e)
        return api_response(False, None,
                            document_failure_detail(e, action="preview the TDS on this bill"))


def _duplicate_bill_id(db, client_id: str, vendor_id: str,
                       bill_no: Optional[str]) -> Optional[str]:
    """The id of a live bill already carrying this vendor's invoice number.

    Matched the way migration 313's unique index matches — case- and
    whitespace-insensitively, ignoring cancelled and soft-deleted bills, and
    ignoring a blank number. The index is the real guard and closes the direct
    PostgREST path too; this exists so the API can say something a CA can act
    on instead of surfacing a constraint name.

    The two must agree. If this is ever loosened without loosening the index,
    the CA gets a raw 23505; if the index is loosened without this, duplicates
    return. tests/test_no_duplicate_purchase_bill.py holds them together.
    """
    key = (bill_no or "").strip().lower()
    if db is None or not key or not client_id or not vendor_id:
        return None
    try:
        rows = (db.table("purchase_bills")
                .select("id, bill_no, status")
                .eq("client_id", client_id).eq("vendor_id", vendor_id)
                .neq("status", "cancelled").is_("deleted_at", "null")
                .execute().data) or []
    except Exception:                                           # noqa: BLE001
        # A failed lookup must not block a legitimate bill — the index still
        # refuses a real duplicate, and this only chooses the wording.
        return None
    for r in rows:
        if (r.get("bill_no") or "").strip().lower() == key:
            return r.get("id")
    return None


def _near_duplicates(db, client_id: str, vendor_id: str, *, bill_no,
                     bill_date, total_paise: int) -> list[dict]:
    """Live bills of the same vendor this one may be a second copy of.

    The EXACT check above refuses; this one only reports, and the difference
    is deliberate — see domain/purchases/near_duplicate for why two identical
    bills on one day are lawful and common. A failed lookup returns nothing:
    a warning that could not be computed must never block a legitimate bill.
    """
    if db is None or not client_id or not vendor_id:
        return []
    try:
        rows = (db.table("purchase_bills")
                .select("id, bill_no, bill_date, total_paise, status, deleted_at")
                .eq("client_id", client_id).eq("vendor_id", vendor_id)
                .neq("status", "cancelled").is_("deleted_at", "null")
                .order("bill_date", desc=True).limit(200)
                .execute().data) or []
    except Exception:                                           # noqa: BLE001
        return []
    return [asdict(n) for n in near_duplicate.near_duplicates(
        bill_no=bill_no, bill_date=bill_date,
        total_paise=int(total_paise or 0), existing=rows)]


def _duplicate_bill_message(bill_no: str, existing_id: str) -> str:
    return (
        f"Bill {bill_no} is already recorded against this vendor "
        f"(bill {existing_id}). Booking a supplier invoice twice double-counts "
        f"the expenditure, claims the input GST credit twice under CGST s.16, "
        f"and — where TDS was deducted — files the deductee twice. Open the "
        f"existing bill, or cancel it first if this one replaces it."
    )


def _compute_bill_lines_and_totals(
    lines_data: list[dict],
    is_interstate: bool,
    vendor: dict,
    bill_date: str,
    firm_id: str,
    dc,
    db=None,
    exclude_bill_id: Optional[str] = None,
    is_reverse_charge: bool = False,
) -> dict:
    """Compute GST-split lines + vendor TDS for a purchase bill, in integer
    paise. Shared by create (_create_purchase_bill_core) and update
    (update_purchase_bill's draft-only full line edit) so the two paths can
    never silently compute different totals for identical inputs — the same
    class of bug this codebase has hit before with duplicated financial math.

    `exclude_bill_id` excludes the bill being edited from the TDS FY-prior
    aggregate query: on update the bill already exists with its own (stale)
    taxable_amount_paise, which would otherwise double-count against itself
    when checking the §194C-style aggregate threshold. Always None on create,
    since the bill doesn't exist yet.

    `is_reverse_charge` — CGST Act §9(3)/(4): on an RCM inward supply the
    VENDOR invoices without tax; the recipient self-assesses the GST (paid in
    cash via GSTR-3B Table 3.1(d), ITC claimable per §16). The GST components
    are therefore still computed and stored (they drive 3B, ITC, and the RCM
    liability journal lines), but the amount OWED TO THE VENDOR — total_paise
    / line_total_paise / net_payable — is the taxable value only. Previously
    RCM bills were computed identically to normal bills, overstating Trade
    Payables by the GST the vendor never charged.
    """
    computed_lines: list[dict] = []
    total_taxable = 0
    total_cgst    = 0
    total_sgst    = 0
    total_igst    = 0
    # CGST Act §17(5): GST on itc_eligible=false lines is BLOCKED input tax
    # credit — tracked separately so it can be excluded from the GSTR-3B ITC
    # claim (Table 4(A)) and reported instead under Table 4(D)(1). It still
    # counts toward the vendor's total_paise/net_payable (the bill amount
    # owed is unaffected by ITC eligibility, only the ITC claim is).
    total_ineligible_cgst = 0
    total_ineligible_sgst = 0
    total_ineligible_igst = 0

    for ln in lines_data:
        qty          = ln.get("quantity", 1)
        rate_paise   = int(ln.get("rate_paise", 0))
        # Model uses gst_rate_percent (e.g. 18.0), convert to bps (10000 bps = 100%)
        gst_rate_percent = float(ln.get("gst_rate_percent", 0) or ln.get("gst_rate_bps", 0) / 100)
        gst_rate_bps = int(round(gst_rate_percent * 100))
        taxable      = int(Decimal(str(qty)) * rate_paise)
        cgst, sgst, igst = _compute_line_gst(taxable, gst_rate_bps, is_interstate)
        itc_eligible = ln.get("itc_eligible", True)

        total_taxable += taxable
        total_cgst    += cgst
        total_sgst    += sgst
        total_igst    += igst
        if not itc_eligible:
            total_ineligible_cgst += cgst
            total_ineligible_sgst += sgst
            total_ineligible_igst += igst

        computed_lines.append({
            "description":          ln.get("description", ""),
            "hsn_sac":              ln.get("hsn_sac", ""),
            "expense_account_id":   ln.get("expense_account_id"),
            "quantity":             qty,
            "unit":                 ln.get("unit") or "NOS",
            "rate_paise":           rate_paise,
            "gst_rate_bps":         gst_rate_bps,
            "taxable_amount_paise": taxable,
            "cgst_paise":           cgst,
            "sgst_paise":           sgst,
            "igst_paise":           igst,
            # RCM: the vendor's line total excludes the self-assessed GST
            # (CGST Act §9(3)/(4) — see the docstring above).
            "line_total_paise":     taxable if is_reverse_charge else taxable + cgst + sgst + igst,
            "service_catalogue_id": ln.get("service_catalogue_id"),
            "itc_eligible":         itc_eligible,
            "blocked_credit_reason": ln.get("blocked_credit_reason"),
        })

    # Multi-Currency (Phase 3): the line totals above are in the txn currency's
    # minor units; convert each to base (INR) paise (sum = base total, exact GL
    # balance) BEFORE TDS, because statutory TDS is always computed on the
    # INR-equivalent taxable.
    txn_taxable   = total_taxable
    txn_total_gst = total_cgst + total_sgst + total_igst
    # RCM: the vendor never charged the GST, so the bill total (what the
    # vendor is owed) is the taxable value alone — the self-assessed GST
    # lives in the cgst/sgst/igst columns for 3B/ITC/journal, not in the AP.
    txn_total     = txn_taxable if is_reverse_charge else txn_taxable + txn_total_gst
    total_taxable = dc.to_base(total_taxable)
    total_cgst    = dc.to_base(total_cgst)
    total_sgst    = dc.to_base(total_sgst)
    total_igst    = dc.to_base(total_igst)
    total_ineligible_cgst = dc.to_base(total_ineligible_cgst)
    total_ineligible_sgst = dc.to_base(total_ineligible_sgst)
    total_ineligible_igst = dc.to_base(total_ineligible_igst)
    total_gst_sum = total_cgst + total_sgst + total_igst
    total_paise   = total_taxable if is_reverse_charge else total_taxable + total_gst_sum

    # ── TDS — routed through the central engine (domain/tds/tds_computer).
    # No inline rate maths: the engine owns thresholds, FY aggregation, payee-type
    # rates, unknown-section handling and the rate bound (audit H5/H6/L1/L6).
    # TDS base is the taxable amount, excluding GST — IT Act §194C/194I/194J.
    tds_paise = 0
    tds_rate_bps = 0
    tds_surcharge_paise = 0
    tds_cess_paise = 0
    tds_nature = None
    tds_basis = None
    tds_citation = ""
    # Why the resident figure is what it is. Not persisted; the preview shows
    # it. None on a s.195 bill, where tds_basis carries the reason instead.
    tds_resident_why = None
    tds_advance_adjusted_paise = 0
    tds_certificate_no = None
    tds_section = (vendor.get("tds_section") or "").upper().strip() or None
    if vendor.get("tds_applicable"):
        # WHICH SECTION CHARGES IS DECIDED IN services/vendor_tds.py, and so is
        # how much. Both resolvers used to live in this router as private
        # functions, which is why the payment path — where §194 charges the
        # EARLIER of credit and payment — had no engine to call and withheld
        # nothing on an advance (PUR-10). One module, two callers.
        _w = vendor_tds.resolve_withholding(
            vendor, total_taxable, bill_date, firm_id, db,
            exclude_bill_id=exclude_bill_id,
            # Scopes the §197 certificate lookup — the service-role key
            # bypasses RLS, so the app-layer filter is the isolation control.
            client_id=vendor.get("client_id"),
            # Only a bill absorbs an earlier advance: the advance was charged
            # when it was paid, and booking the bill credits the same sum.
            adjust_against_advances=True,
        )
        tds_paise = _w.tds_paise
        tds_rate_bps = _w.rate_bps
        tds_surcharge_paise = _w.surcharge_paise
        tds_cess_paise = _w.cess_paise
        tds_nature = _w.nature
        tds_basis = _w.basis
        tds_citation = _w.citation
        tds_resident_why = _w.why
        tds_advance_adjusted_paise = _w.advance_adjusted_paise
        tds_certificate_no = _w.certificate_no
        tds_section = _w.section
    # ── The deduction is bounded by the payment ────────────────────────────
    # TDS is withheld FROM a sum paid or credited, so it cannot exceed that
    # sum. That was academic while the charge fell on the marginal bill —
    # tds was at most 20% of the taxable value — and became real the moment the
    # charge moved to the FY AGGREGATE: the bill that crosses a threshold
    # carries the whole year's tax, which can be many times its own value.
    #
    # A §194J vendor billing ₹49,000 (nil, under the ₹50,000 limit) and then
    # ₹2,000 owes ₹5,100 on the ₹51,000 aggregate against a ₹2,360 bill. Left
    # unbounded this produced net_payable_paise = -₹3,100, and the kernel
    # credits Trade Payables with exactly that figure — against
    # `journal_lines CHECK (credit_paise >= 0)` (migration 003). The entry
    # still BALANCES, so _create_journal's own assertion passed and mock mode
    # wrote it happily; production answered 23514, receive_purchase_bill rolled
    # the status back, and the bill was stuck as a draft for ever. Migration
    # 278's generated outstanding_paise went negative with it.
    #
    # THE SHORTFALL IS NOT LOST. fy_prior_tds_paise sums what earlier bills
    # ACTUALLY withheld, so the next bill to this payee re-charges the
    # difference automatically — the same §200 credit that stops the aggregate
    # being taxed twice carries an under-deduction forward. No state is needed
    # for it and nothing has to remember.
    deductible_paise = min(tds_paise, total_paise)
    tds_shortfall_paise = tds_paise - deductible_paise
    tds_paise = deductible_paise
    net_payable_paise = total_paise - tds_paise
    total_gst_paise = total_cgst + total_sgst + total_igst   # M1: persist on the bill

    return {
        "computed_lines":       computed_lines,
        "taxable_amount_paise": total_taxable,
        "cgst_paise":           total_cgst,
        "sgst_paise":           total_sgst,
        "igst_paise":           total_igst,
        "total_paise":          total_paise,
        "total_gst_paise":      total_gst_paise,
        # CGST Act §17(5) — blocked credit, excluded from the GSTR-3B ITC
        # claim (see the itc_eligible accumulation above).
        "ineligible_itc_cgst_paise": total_ineligible_cgst,
        "ineligible_itc_sgst_paise": total_ineligible_sgst,
        "ineligible_itc_igst_paise": total_ineligible_igst,
        # On a s.195 bill tds_paise is the TOTAL withheld (base + surcharge +
        # cess) while tds_rate_bps is the BASE rate, so the two no longer
        # satisfy tds_paise = taxable * rate / 10000 the way every
        # resident-section bill does. That is deliberate: Form 27Q's deductee
        # annexure asks for the rate tax was deducted at and reports surcharge
        # and cess in their own columns. Pinned by a test.
        "tds_paise":            tds_paise,
        "tds_rate_bps":         tds_rate_bps,
        "tds_section":          tds_section,
        # How much of this bill's value was already charged as an advance and
        # is therefore NOT charged again (§194 — credit or payment, whichever
        # is earlier). Stored because the next bill has to know the pool was
        # consumed; see services/vendor_tds.aggregate_so_far.
        "tds_advance_adjusted_paise": tds_advance_adjusted_paise,
        "tds_certificate_no": tds_certificate_no,
        "tds_surcharge_paise":  tds_surcharge_paise,
        "tds_cess_paise":       tds_cess_paise,
        "tds_nature_of_income": tds_nature,
        "tds_basis":            tds_basis,
        # Not persisted — the sentence the engine resolved on, carried through
        # the computed dict so the register can record it against a nil.
        "_tds_citation":        tds_citation,
        # Also not persisted: WHY the resident figure is what it is. tds_basis
        # above is the §195 basis and stays that — it is a stored column and
        # widening what it means would change what every existing row says.
        "_tds_resident_reason": tds_resident_why,
        "net_payable_paise":    net_payable_paise,
        # What the FY aggregate demanded that this bill was too small to
        # withhold. Not persisted and not a column: it is a fact about this
        # bill's arithmetic, and the next bill to the same payee recovers it.
        # Reported so a CA is told the year's liability is not yet fully
        # deducted rather than inferring it from a net payable of nil — an
        # under-deduction carries §201(1A) interest at 1% a month until it is.
        "_tds_shortfall_paise": tds_shortfall_paise,
        # Currency columns (INR identity leaves them inert).
        "txn_taxable":          txn_taxable,
        "txn_total_gst":        txn_total_gst,
        "txn_total":            txn_total,
        "txn_net_payable":      txn_total - dc.to_txn(tds_paise),
    }


def _resolve_bill_currency(db, firm_id: str, data: dict, current_user: dict):
    """The bill's frozen currency and rate. INR / feature-off → identity.

    Extracted from _create_purchase_bill_core for the TDS preview, which has to
    compute on the same base: on a foreign-currency bill the withholding is on
    the INR value at the frozen rate, so a preview using a different rate shows
    a different tax.
    """
    from domain.currency.document_currency import resolve_document_currency, identity_currency
    client_id = data["client_id"]
    req_ccy = (data.get("currency") or "INR").strip().upper()
    if _USE_MOCK or req_ccy == "INR":
        return identity_currency(data["bill_date"])
    _firm_row = (db.table("firms").select("multi_currency_entitled").eq("id", firm_id).limit(1).execute().data or [None])[0]
    _client_mc = (db.table("clients").select("functional_currency, multi_currency_enabled").eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data or [None])[0]
    return resolve_document_currency(
        db, _firm_row, _client_mc, currency=req_ccy,
        exchange_rate=data.get("exchange_rate"), rate_date=data["bill_date"],
        rate_selected_by=current_user.get("id"))


def _resolve_vendor_and_interstate(
    firm_id: str, client_id: str, vendor_id: str, bulk_cache: Optional[dict] = None,
) -> tuple[dict, bool, object]:
    """The vendor row, whether the supply is interstate, and the db handle.

    Extracted VERBATIM from _create_purchase_bill_core so the TDS preview
    endpoint resolves the vendor exactly as the save does. The preview exists
    to show the CA the figure the save will produce; resolving the vendor a
    second way is how the two start disagreeing again, which is the whole of
    TDS-14.
    """
    db = None
    if _USE_MOCK:
        # Look up vendor from in-memory store; fall back to safe defaults
        from routers.vendors import MOCK_VENDORS
        vendor = next((v for v in MOCK_VENDORS if v.get("id") == vendor_id), None)
        if vendor is None:
            vendor = {"tds_applicable": False, "tds_section": None, "tds_rate_bps": 0, "state_code": "27"}
        is_interstate = False
    else:
        from core.supabase_client import get_supabase
        db = get_supabase()

        if bulk_cache is not None:
            vendor = bulk_cache["vendor"]
            if not vendor:
                raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
        else:
            # Fetch vendor for TDS info and state code (firm- AND client-scoped
            # — never resolve a vendor belonging to a DIFFERENT client of the
            # same firm, which would book this client's bill using another
            # client's vendor's TDS section/PAN/state_code).
            v_resp = (db.table("vendors").select("*")
                      .eq("id", vendor_id).eq("firm_id", firm_id).eq("client_id", client_id)
                      .limit(1).execute())
            if not v_resp.data:
                raise HTTPException(status_code=404, detail=f"Vendor {vendor_id} not found")
            vendor = v_resp.data[0]
        # Business guard: never book a bill against a deactivated vendor.
        if vendor.get("is_active") is False:
            raise HTTPException(status_code=422, detail="This vendor is inactive. Reactivate the vendor before booking a bill.")

        # Determine is_interstate
        vendor_state = vendor.get("state_code") or _get_state_code_from_gstin(vendor.get("gstin")) or ""
        if bulk_cache is not None:
            client_state = _get_state_code_from_gstin(bulk_cache.get("client_gstin")) or ""
        else:
            client_resp  = db.table("clients").select("gstin").eq("id", client_id).eq("firm_id", firm_id).limit(1).execute()
            client_state = ""
            if client_resp.data:
                client_state = _get_state_code_from_gstin(client_resp.data[0].get("gstin")) or ""
        is_interstate = bool(vendor_state and client_state and vendor_state != client_state)
    return vendor, is_interstate, db


def _create_purchase_bill_core(data: dict, current_user: dict, bulk_cache: Optional[dict] = None) -> dict:
    """Shared purchase-bill-creation logic used by both create_purchase_bill
    and the bulk import endpoint below — extracted verbatim (no behavior
    change for a single create: bulk_cache is always None there) so the CSV
    importer can create many bills in ONE request instead of firing one POST
    per bill. Raises HTTPException on failure; returns the created bill dict
    (with lines) on success.

    bulk_cache (bulk import only — see bulk_create_purchase_bills, which
    pre-fetches it once per request instead of once per bill):
      "vendor": this bill's vendor row (already resolved by the caller)
      "client_gstin": the buying client's GSTIN (for the interstate check)
        — shared across the whole batch per client_id.
    Skips the per-bill audit/timeline writes in bulk mode — both are
    documented non-fatal, best-effort UX/audit metadata (never read by
    GST/TDS/journal code); bulk_create_purchase_bills writes one summary
    audit + timeline entry for the whole batch afterward instead."""
    required = ["client_id", "vendor_id", "bill_date", "lines"]
    for field in required:
        if not data.get(field):
            raise HTTPException(status_code=422, detail=f"{field} is required")

    firm_id   = current_user.get("firm_id")
    client_id = data["client_id"]
    vendor_id = data["vendor_id"]
    lines_data = data.get("lines", [])
    if not lines_data:
        raise HTTPException(status_code=422, detail="At least one line item is required")

    vendor, is_interstate, db = _resolve_vendor_and_interstate(
        firm_id or "", client_id, vendor_id, bulk_cache)

    # Snapshot credit terms onto the bill. The vendor's credit_days is the
    # DEFAULT; an explicit due_date or credit_days on the request overrides
    # it. Mirrors sales_invoices.py's identical snapshot for customers.
    eff_due_date, eff_credit_days = resolve_credit_terms(
        data["bill_date"], data.get("due_date"), data.get("credit_days"),
        vendor.get("credit_days"),
    )

    dc = _resolve_bill_currency(db, firm_id or "", data, current_user)

    is_reverse_charge = bool(data.get("is_reverse_charge", False))
    computed = _compute_bill_lines_and_totals(
        lines_data, is_interstate, vendor, data["bill_date"], firm_id or "", dc,
        db=(db if not _USE_MOCK else None),
        is_reverse_charge=is_reverse_charge,
    )
    computed_lines    = computed["computed_lines"]
    total_taxable     = computed["taxable_amount_paise"]
    total_cgst        = computed["cgst_paise"]
    total_sgst        = computed["sgst_paise"]
    total_igst        = computed["igst_paise"]
    total_paise       = computed["total_paise"]
    if total_paise <= 0:
        raise HTTPException(status_code=422, detail="Purchase bill total must be positive.")
    total_gst_paise   = computed["total_gst_paise"]
    ineligible_itc_cgst_paise = computed["ineligible_itc_cgst_paise"]
    ineligible_itc_sgst_paise = computed["ineligible_itc_sgst_paise"]
    ineligible_itc_igst_paise = computed["ineligible_itc_igst_paise"]
    tds_paise         = computed["tds_paise"]
    tds_rate_bps      = computed["tds_rate_bps"]
    tds_section       = computed["tds_section"]
    tds_surcharge_paise = computed["tds_surcharge_paise"]
    tds_cess_paise      = computed["tds_cess_paise"]
    tds_nature_of_income = computed["tds_nature_of_income"]
    tds_basis            = computed["tds_basis"]
    tds_advance_adjusted_paise = computed["tds_advance_adjusted_paise"]
    tds_certificate_no = computed["tds_certificate_no"]
    net_payable_paise = computed["net_payable_paise"]

    # Currency columns (INR identity leaves them inert). Foreign net payable is
    # the foreign total less TDS expressed in the txn currency at the frozen rate.
    _ccy_cols = {
        "txn_currency":     dc.currency,
        "exchange_rate":    str(dc.rate),
        "txn_taxable":      computed["txn_taxable"],
        "txn_total_gst":    computed["txn_total_gst"],
        "txn_total":        computed["txn_total"],
        "txn_net_payable":  computed["txn_net_payable"],
        "rate_source":      dc.rate_source,
        "rate_type":        dc.rate_type,
        "rate_date":        dc.rate_date,
        "rate_selected_by": dc.rate_selected_by,
        "rate_overridden":  dc.rate_overridden,
    }

    # Validate posting date is not in a locked financial year (migration 020).
    # Memoized per FY within a bulk batch (bulk_cache carries the cache dict)
    # — see validate_posting_date_cached's docstring.
    period_validation_service.validate_posting_date_cached(
        firm_id or "", data["bill_date"],
        bulk_cache.get("locked_fy_cache") if bulk_cache is not None else None,
    )
    # ...and not inside a period whose GSTR-3B has already been filed. The FY
    # lock above is the CA's own switch; this is the portal's. A late March bill
    # booked in June carries ITC the filed March 3B never claimed, and §16(4)
    # says where that credit actually goes: the CURRENT return, not the closed
    # one. The sales side has refused this on create since SALES-15; the
    # purchase side is the half that matters most, because a bill is a CLAIM.
    # Memoized on its OWN cache, not the FY one above: that key is the FIRM's
    # year, and a filed return is a fact about one client and one month, so a
    # year-keyed entry would report March's filed 3B over an open February.
    if not _USE_MOCK:
        from core.supabase_client import get_supabase
        period_lock_service.assert_open(
            get_supabase(), firm_id or "", client_id, data["bill_date"],
            bulk_cache.get("period_lock_cache") if bulk_cache is not None else None)

    if _USE_MOCK:
        bill_id = str(uuid.uuid4())
        bill = {
            "id":                    bill_id,
            "firm_id":               firm_id,
            "client_id":             client_id,
            "vendor_id":             vendor_id,
            "bill_no":               data.get("bill_no", ""),
            "our_reference":         data.get("our_reference"),
            "bill_date":             data["bill_date"],
            "due_date":              eff_due_date,
            "credit_days":           eff_credit_days,
            "is_interstate":         is_interstate,
            "taxable_amount_paise":  total_taxable,
            "cgst_paise":            total_cgst,
            "sgst_paise":            total_sgst,
            "igst_paise":            total_igst,
            "total_paise":           total_paise,
            "total_gst_paise":       total_gst_paise,
            "ineligible_itc_cgst_paise": ineligible_itc_cgst_paise,
            "ineligible_itc_sgst_paise": ineligible_itc_sgst_paise,
            "ineligible_itc_igst_paise": ineligible_itc_igst_paise,
            "tds_paise":             tds_paise,
            "tds_rate_bps":          tds_rate_bps,
            "tds_section":           tds_section,
            "tds_surcharge_paise":   tds_surcharge_paise,
            "tds_cess_paise":        tds_cess_paise,
            "tds_nature_of_income":  tds_nature_of_income,
            "tds_basis":             tds_basis,
            "tds_advance_adjusted_paise": tds_advance_adjusted_paise,
            "tds_certificate_no": tds_certificate_no,
            "is_reverse_charge":     is_reverse_charge,
            "net_payable_paise":     net_payable_paise,
            "status":                "draft",
            # Provenance, carried THROUGH rather than decided here: the
            # Purchases page badges a bill with `is_ai_extracted` and the
            # extraction blob is what a CA compares the typed figures against.
            # Absent on every ordinary create, which is the column's default.
            "is_ai_extracted":       bool(data.get("is_ai_extracted", False)),
            "ai_extraction_data":    data.get("ai_extraction_data"),
            "notes":                 data.get("notes", ""),
            "document_url":          data.get("document_url"),
            # Rule 37BB paperwork, recorded not filed — see PurchaseBillIn.
            "form_15ca_ack_no":      data.get("form_15ca_ack_no"),
            "form_15ca_filed_on":    data.get("form_15ca_filed_on"),
            "form_15cb_udin":        data.get("form_15cb_udin"),
            "created_at":            datetime.now(timezone.utc).isoformat(),
            **_ccy_cols,
            "lines":                 computed_lines,
        }
        MOCK_PURCHASE_BILLS.append(bill)
        for ln in computed_lines:
            ln["id"]      = str(uuid.uuid4())
            ln["bill_id"] = bill_id
            MOCK_PURCHASE_BILL_LINES.append(ln)
        return bill

    bill_payload = {
        "firm_id":               firm_id,
        "client_id":             client_id,
        "vendor_id":             vendor_id,
        "bill_no":               data.get("bill_no", ""),
        "our_reference":         data.get("our_reference"),
        "bill_date":             data["bill_date"],
        "due_date":              eff_due_date,
        "credit_days":           eff_credit_days,
        "is_interstate":         is_interstate,
        "taxable_amount_paise":  total_taxable,
        "cgst_paise":            total_cgst,
        "sgst_paise":            total_sgst,
        "igst_paise":            total_igst,
        "total_paise":           total_paise,
        "total_gst_paise":       total_gst_paise,
        "ineligible_itc_cgst_paise": ineligible_itc_cgst_paise,
        "ineligible_itc_sgst_paise": ineligible_itc_sgst_paise,
        "ineligible_itc_igst_paise": ineligible_itc_igst_paise,
        "tds_paise":             tds_paise,
        "tds_rate_bps":          tds_rate_bps,
        "tds_section":           tds_section,
        "tds_surcharge_paise":   tds_surcharge_paise,
        "tds_cess_paise":        tds_cess_paise,
        "tds_nature_of_income":  tds_nature_of_income,
        "tds_basis":             tds_basis,
        "tds_advance_adjusted_paise": tds_advance_adjusted_paise,
        "tds_certificate_no": tds_certificate_no,
        "is_reverse_charge":     is_reverse_charge,
        "net_payable_paise":     net_payable_paise,
        "status":                "draft",
        "is_ai_extracted":       bool(data.get("is_ai_extracted", False)),
        "ai_extraction_data":    data.get("ai_extraction_data"),
        "notes":                 data.get("notes", ""),
        "document_url":          data.get("document_url"),
        # Rule 37BB paperwork, recorded not filed — see PurchaseBillIn.
        "form_15ca_ack_no":      data.get("form_15ca_ack_no"),
        "form_15ca_filed_on":    data.get("form_15ca_filed_on"),
        "form_15cb_udin":        data.get("form_15cb_udin"),
        "created_at":            datetime.now(timezone.utc).isoformat(),
        **_ccy_cols,
    }

    # One supplier invoice, one bill. The unique index of migration 313 is the
    # real guard — it closes the bulk path and the direct PostgREST writes too
    # — but a CA meeting a raw 23505 learns nothing, so the wording happens
    # here. Walking a client with foreign suppliers through a year booked the
    # same invoice twice and got two posted journals and two Form 27Q rows.
    _dup = _duplicate_bill_id(db, bill_payload.get("client_id"),
                              bill_payload.get("vendor_id"),
                              bill_payload.get("bill_no"))
    if _dup:
        raise HTTPException(
            status_code=409,
            detail=_duplicate_bill_message(bill_payload.get("bill_no") or "", _dup))

    # The number is DIFFERENT but the bill may not be (PUR-32). Read before
    # the insert so the new row cannot report itself, and warn rather than
    # refuse — two identical bills from one supplier on one day are lawful.
    # Not in bulk: an import of 400 bills would be 400 extra reads to produce
    # a warning nobody is looking at while a CSV uploads. The exact guard
    # above (and the batch's own pre-fetch) still refuses a true duplicate.
    _near = [] if bulk_cache is not None else _near_duplicates(
        db, bill_payload.get("client_id"), bill_payload.get("vendor_id"),
        bill_no=bill_payload.get("bill_no"),
        bill_date=bill_payload.get("bill_date"),
        total_paise=bill_payload.get("total_paise") or 0)

    bill_resp = db.table("purchase_bills").insert(bill_payload).execute()  # type: ignore[possibly-undefined]
    bill      = bill_resp.data[0] if bill_resp.data else bill_payload
    bill_id   = bill.get("id", str(uuid.uuid4()))

    line_payloads = [
        {
            "bill_id":               bill_id,
            "description":           ln["description"],
            "hsn_sac":               ln["hsn_sac"],
            "expense_account_id":    ln.get("expense_account_id"),
            "quantity":              ln["quantity"],
            "unit":                  ln.get("unit") or "NOS",
            "rate_paise":            ln["rate_paise"],
            "gst_rate_bps":          ln["gst_rate_bps"],
            "taxable_amount_paise":  ln["taxable_amount_paise"],
            "cgst_paise":            ln["cgst_paise"],
            "sgst_paise":            ln["sgst_paise"],
            "igst_paise":            ln["igst_paise"],
            "line_total_paise":      ln["line_total_paise"],
            # BUG FIX (audit): this key was missing entirely, so a product
            # picked via ServiceCataloguePicker on a Purchase Bill line never
            # actually persisted — apply_purchase_to_inventory's later SELECT
            # of this column always saw NULL, silently skipping stock-in for
            # every bill ever created through this path.
            "service_catalogue_id":  ln.get("service_catalogue_id"),
            # CGST Act §17(5) — see migration 240.
            "itc_eligible":          ln.get("itc_eligible", True),
            "blocked_credit_reason": ln.get("blocked_credit_reason"),
        }
        for ln in computed_lines
    ]
    lines_resp = db.table("purchase_bill_lines").insert(line_payloads).execute()  # type: ignore[possibly-undefined]
    bill["lines"] = lines_resp.data or computed_lines

    # Per-bill audit/timeline writes — skipped in bulk mode (see the
    # bulk_cache docstring above): bulk_create_purchase_bills writes one
    # summary audit + timeline entry for the whole batch instead of firm_id/
    # client_id-identical rows repeated once per imported bill.
    if bulk_cache is None:
        log_event(
            firm_id or "", "purchase_bill", bill_id,
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=bill,
        )
        timeline_service.log(
            client_id, "accounting", "Purchase Bill Created",
            f"Bill {bill.get('bill_no', '')} for ₹{bill.get('total_paise', 0) // 100:,} created (draft)",
            "info", firm_id=firm_id or "",
            entity_type="purchase_bill", entity_id=bill_id,
            amount_paise=bill.get("total_paise"), actor_id=current_user.get("auth_user_id"),
        )
    # Carried on the bill rather than raised: the CA has just saved it, and the
    # answer to "is this the same bill twice" is a comparison only they can
    # make. Absent (rather than []) in mock mode, where there is nothing to
    # compare against and an empty list would read as "checked, and clean".
    if _near:
        bill["near_duplicates"] = _near
    return bill


class _BulkPurchaseBillsIn(BaseModel):
    bills: list[dict]


@router.post("/bulk")
def bulk_create_purchase_bills(
    payload: _BulkPurchaseBillsIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Create many purchase bills in ONE request.

    The CSV importer used to fire one POST /api/purchase-bills/ per bill — for
    a 100-row import that's 100 sequential network round-trips, and it
    multiplies badly when many firms import concurrently. This endpoint loops
    the exact same _create_purchase_bill_core logic server-side (no behavior
    change, no duplicated GST/TDS business rules), collapsing N round-trips
    to roughly 1 for the WHOLE batch: the vendor and client rows are
    pre-fetched ONCE here (bulk_cache), mirroring bulk_create_invoices —
    without it, every bill re-fetches the SAME vendor/client rows a bulk
    import naturally repeats many times (several bills per vendor). A bad
    row is reported per-item and does not abort the rest of the batch —
    matches the existing CSV-import UX (partial success with a per-row
    error list).
    """
    _assert_batch_scope(current_user, [r.get("client_id") if isinstance(r, dict) else None for r in payload.bills])
    items = payload.bills
    created: list[dict] = []
    errors: list[dict] = []
    firm_id = current_user.get("firm_id")

    parsed: list[tuple[int, str, PurchaseBillIn]] = []
    for i, raw in enumerate(items):
        bill_no = raw.get("bill_no", "") if isinstance(raw, dict) else ""
        try:
            parsed.append((i, bill_no, PurchaseBillIn(**raw)))
        except PydanticValidationError as e:
            errors.append({"index": i, "bill_no": bill_no, "error": str(e.errors()[0].get("msg", "Invalid bill data")) if e.errors() else "Invalid bill data"})

    # ── Duplicate guard (financial-record integrity) ────────────────────────
    # A large CSV import can legitimately take long enough that the browser's
    # own fetch times out or drops the connection while the backend is still
    # (or has already finished) writing the batch — CsvImportModal.handleImport
    # tells the user their rows "may have already been created" for exactly
    # this reason. Without a check here, retrying/re-uploading the same file
    # silently doubles (or triples) every bill: same vendor, same bill_no, same
    # amounts, each with its own status and, once received, its own posted
    # journal — double-counted purchases and input GST credit. Mirrors the
    # existing GSTIN/PAN dedup guard on Customers bulk-create (routers/
    # customers.py bulk_create_customers): one pre-fetch of existing
    # (client_id, vendor_id, bill_no) keys, checked before insert, duplicates
    # reported back as `skipped` instead of silently re-created.
    existing_keys: set[tuple[str, str, str]] = set()
    if parsed and not _USE_MOCK:
        from core.supabase_client import get_supabase
        db = get_supabase()
        client_ids_for_dedup = list({p[2].client_id for p in parsed})
        CHUNK = 200
        for i in range(0, len(client_ids_for_dedup), CHUNK):
            chunk = client_ids_for_dedup[i:i + CHUNK]
            # neq("status","cancelled") added to agree with migration 313's
            # index: cancelling is a credit undone, so a CA who cancels INV-001
            # because the amount was wrong and re-uploads it corrected is doing
            # the right thing. Without this the corrected row was reported as a
            # duplicate and silently SKIPPED — the guard refusing the fix.
            resp = (db.table("purchase_bills").select("client_id, vendor_id, bill_no")
                    .eq("firm_id", firm_id).in_("client_id", chunk)
                    .neq("status", "cancelled").is_("deleted_at", None).execute())
            for r in (resp.data or []):
                existing_keys.add((r.get("client_id"), r.get("vendor_id"), (r.get("bill_no") or "").strip().lower()))

    skipped: list[dict] = []
    deduped: list[tuple[int, str, PurchaseBillIn]] = []
    for i, bill_no, data in parsed:
        key = (data.client_id, data.vendor_id, (bill_no or "").strip().lower())
        if bill_no and key in existing_keys:
            skipped.append({"index": i, "bill_no": bill_no, "reason": "A bill with this vendor and bill number already exists"})
            continue
        existing_keys.add(key)  # also catches the same bill_no repeated within this same batch
        deduped.append((i, bill_no, data))
    parsed = deduped

    vendors_by_id: dict = {}
    client_gstin_by_id: dict = {}
    if parsed and not _USE_MOCK:
        from core.supabase_client import get_supabase
        db = get_supabase()
        vendor_ids = list({p[2].vendor_id for p in parsed})
        client_ids = list({p[2].client_id for p in parsed})
        CHUNK = 200  # stay well under any PostgREST IN-list/URL-length limit
        for i in range(0, len(vendor_ids), CHUNK):
            chunk = vendor_ids[i:i + CHUNK]
            # Scoped by client_id (not just firm_id) so a batch row can never
            # resolve a vendor belonging to a DIFFERENT client of the same
            # firm — keyed by (client_id, vendor_id), the same compound key
            # _create_purchase_bill_core now requires for the single-bill path.
            resp = (db.table("vendors").select("*")
                    .eq("firm_id", firm_id).in_("id", chunk).in_("client_id", client_ids).execute())
            for r in (resp.data or []):
                vendors_by_id[(r["client_id"], r["id"])] = r
        for i in range(0, len(client_ids), CHUNK):
            chunk = client_ids[i:i + CHUNK]
            resp = db.table("clients").select("id, gstin").eq("firm_id", firm_id).in_("id", chunk).execute()
            for r in (resp.data or []):
                client_gstin_by_id[r["id"]] = r.get("gstin")

    # Locked-FY status is firm-wide and cannot change mid-request — shared and
    # mutated across the whole loop (see validate_posting_date_cached) so a
    # batch spanning 2 financial years costs 2 RPC calls, not one per bill.
    locked_fy_cache: dict = {}
    # The client lock is the same question at a finer grain — one answer per
    # (client, date) rather than per FY, since a filed GSTR-3B closes a month.
    period_lock_cache: dict = {}

    for i, bill_no, data in parsed:
        try:
            bulk_cache = None
            if not _USE_MOCK:
                bulk_cache = {
                    "vendor": vendors_by_id.get((data.client_id, data.vendor_id)),
                    "client_gstin": client_gstin_by_id.get(data.client_id),
                    "locked_fy_cache": locked_fy_cache,
                    "period_lock_cache": period_lock_cache,
                }
            bill = _create_purchase_bill_core(data.model_dump(), current_user, bulk_cache=bulk_cache)
            created.append(bill)
        except HTTPException as e:
            errors.append({"index": i, "bill_no": bill_no, "error": e.detail})
        except Exception as e:
            _logger.error("bulk_create_purchase_bills item %d failed: %s", i, e, exc_info=True)
            errors.append({"index": i, "bill_no": bill_no,
                           "error": document_failure_detail(e, action="create this bill")})

    # One summary audit + timeline entry for the whole batch instead of one
    # per bill (skipped inside _create_purchase_bill_core for bulk_cache
    # calls — see its docstring): a bulk import's real audit-trail question
    # is "who imported N bills and when", not N near-identical entries.
    if created:
        log_event(
            firm_id or "", "purchase_bill", "bulk_import", "create",
            actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
            new_data={"count": len(created), "bill_nos": [c.get("bill_no") for c in created][:100]},
        )
        by_client: dict[str, list[dict]] = {}
        for c in created:
            by_client.setdefault(c.get("client_id", ""), []).append(c)
        for cid, bills in by_client.items():
            if not cid:
                continue
            total = sum(b.get("total_paise", 0) for b in bills)
            timeline_service.log(
                cid, "accounting", "Purchase Bills Imported",
                f"{len(bills)} bill(s) imported via bulk upload, totaling ₹{total // 100:,}.",
                "info", firm_id=firm_id or "",
                entity_type="purchase_bill", amount_paise=total,
                actor_id=current_user.get("auth_user_id"),
            )
    return api_response(True, {"created": created, "errors": errors, "skipped": skipped})


@router.get("/{bill_id}")
def get_purchase_bill(
    bill_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Get a purchase bill with line items."""
    _assert_bill_scope(current_user, bill_id)
    try:
        if _USE_MOCK:
            bill = next((b for b in MOCK_PURCHASE_BILLS if b["id"] == bill_id and not b.get("deleted_at")), None)
            if not bill:
                raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
            bill["lines"] = [ln for ln in MOCK_PURCHASE_BILL_LINES if ln.get("bill_id") == bill_id]
            return api_response(True, bill)

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("purchase_bills").select("*").eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).is_("deleted_at", None).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
        bill = resp.data[0]
        lines_resp = db.table("purchase_bill_lines").select("*").eq("bill_id", bill_id).execute()
        bill["lines"] = lines_resp.data or []
        return api_response(True, bill)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_purchase_bill: %s", e)
        return api_response(False, None, f"Unable to complete purchase bill operation: {e}")


@router.get("/{bill_id}/document-url")
def get_purchase_bill_document_url(
    bill_id: str,
    current_user: dict = Depends(rbac("accounting", "read")),
):
    """Mint a fresh signed URL for the bill's attached original invoice.
    document_url on the bill is a private-bucket storage PATH, not a
    browser-openable URL — signed URLs expire, so one is generated on
    demand here rather than stored (mirrors routers/documents.py's
    get_download_url). 404 when no document is attached."""
    _assert_bill_scope(current_user, bill_id)
    try:
        if _USE_MOCK:
            bill = next((b for b in MOCK_PURCHASE_BILLS if b["id"] == bill_id), None)
            if not bill:
                raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
            if not bill.get("document_url"):
                raise HTTPException(status_code=404, detail="No document attached to this bill")
            return api_response(True, {"url": bill["document_url"]})

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = db.table("purchase_bills").select("document_url").eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
        path = resp.data[0].get("document_url")
        if not path:
            raise HTTPException(status_code=404, detail="No document attached to this bill")
        signed = db.storage.from_("Documents").create_signed_url(path, expires_in=3600)
        url = signed.get("signedURL") if isinstance(signed, dict) else None
        if not url:
            raise HTTPException(status_code=502, detail="Unable to generate a download link. Please try again.")
        return api_response(True, {"url": url})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("get_purchase_bill_document_url: %s", e)
        return api_response(False, None, f"Unable to complete purchase bill operation: {e}")


# Human-readable phrasing for statuses that block deletion.
_BILL_DELETE_BLOCKED = {
    "received":         "a received",
    "partially_paid":   "a partially-paid",
    "paid":             "a paid",
    "cancelled":        "a cancelled",
}


@router.delete("/{bill_id}")
def delete_purchase_bill(
    bill_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Hard-delete a DRAFT purchase bill. Mirrors sales_invoices.py's
    delete_invoice exactly.

    Only drafts may be deleted. Received / partially-paid / paid / cancelled
    bills are protected — they have a posted journal (and, for received
    bills, possible ITC/inventory effects) and must never be removed. A
    draft never appears in any accounting report or ITC computation, so
    removing it has zero effect on the Trial Balance / P&L / Balance Sheet.
    The row is genuinely removed (not soft-deleted): the create/delete
    audit_log events already capture the full document and a status summary
    respectively, independent of whether the row itself still exists.
    """
    _assert_bill_scope(current_user, bill_id)
    try:
        if _USE_MOCK:
            for i, b in enumerate(MOCK_PURCHASE_BILLS):
                if b["id"] == bill_id:
                    st = b.get("status")
                    if st != "draft":
                        raise HTTPException(
                            status_code=422,
                            detail=f"Cannot delete {_BILL_DELETE_BLOCKED.get(st, st)} bill — only drafts can be deleted",
                        )
                    MOCK_PURCHASE_BILLS.pop(i)
                    return api_response(True, {"id": bill_id, "deleted": True})
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        resp = (
            db.table("purchase_bills").select("*")
            .eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).is_("deleted_at", None).limit(1).execute()
        )
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
        bill = resp.data[0]
        st = bill.get("status")
        if st != "draft":
            raise HTTPException(
                status_code=422,
                detail=f"Cannot delete {_BILL_DELETE_BLOCKED.get(st, st)} bill — only drafts can be deleted",
            )

        # Hard delete — draft-only, so purchase_bill_lines cascades automatically
        # (FK ON DELETE CASCADE) and nothing else can reference a still-draft
        # bill (debit notes / purchase credit notes / payments only attach to
        # received bills). The audit_log 'delete' event below (and the 'create'
        # event's full snapshot, logged when the bill was made) survive
        # independently — audit_log.entity_id is a bare text column, not an FK.
        db.table("purchase_bills").delete().eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).execute()

        log_event(
            current_user.get("firm_id", ""), "purchase_bill", bill_id,
            "delete", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            old_data={
                "bill_no":     bill.get("bill_no"),
                "status":      st,
                "total_paise": bill.get("total_paise"),
            },
        )
        return api_response(True, {"id": bill_id, "deleted": True})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("delete_purchase_bill: %s", e)
        return api_response(False, None, f"Unable to complete purchase bill operation: {e}")


# Once a bill is received, only these fields may still change — mirrors the
# same rule on sales invoices (routers/sales_invoices.py:_SOFT_UPDATE_FIELDS).
# line_units is handled separately, always allowed regardless of status.
# The last three are the Form 15CA / 15CB references, and they are here for the
# same reason the shipping bill is on a sales invoice: they come into existence
# AFTER the document. Form 15CB's UDIN is generated when the CA signs the
# certificate; Form 15CA's acknowledgement number only exists once the
# declaration has been filed on the income-tax portal; the remittance itself
# follows the bill. None of the three is a particular of the supplier's
# invoice — they are this client's own compliance references for the payment —
# so CGST s.34 is untouched.
_SOFT_BILL_UPDATE_FIELDS = {"notes", "due_date", "credit_days", "our_reference",
                            "document_url", "form_15ca_ack_no",
                            "form_15ca_filed_on", "form_15cb_udin"}


def _reject_locked_bill_fields(data: dict) -> None:
    """bill_no/bill_date/lines/is_inter_state are locked once a bill is
    received — a correction to any of those needs a Debit Note instead of a
    silent edit (CGST Act §34, same principle as the sales-invoice side)."""
    locked = sorted(set(data.keys()) - _SOFT_BILL_UPDATE_FIELDS)
    if locked:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Cannot change {', '.join(locked)} on a received bill — only "
                "our reference, notes, payment terms, due date and the attached "
                "invoice can still be edited. Issue a Debit Note to correct "
                "anything else (CGST Act §34)."
            ),
        )


@router.patch("/{bill_id}")
def update_purchase_bill(
    bill_id: str,
    data: PurchaseBillUpdateIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Update a purchase bill. DRAFT: full edit. RECEIVED/PARTIALLY_PAID/
    PAID: only our_reference, notes, due_date and line_units may change —
    see _reject_locked_bill_fields. CANCELLED: cannot be updated at all."""
    _assert_bill_scope(current_user, bill_id)
    try:
        data = data.model_dump(exclude_none=True)
        # The request model field is is_inter_state; the DB column is
        # is_interstate — same mapping sales_invoices.py's update_invoice
        # applies (without it, sending this field 400s: no such column).
        if "is_inter_state" in data:
            data["is_interstate"] = data.pop("is_inter_state")
        # Always allowed regardless of status — unit alone never touches
        # rate/quantity/amount/GST.
        line_units = data.pop("line_units", None)

        if _USE_MOCK:
            for i, b in enumerate(MOCK_PURCHASE_BILLS):
                if b["id"] == bill_id:
                    status = b.get("status")
                    if status == "cancelled":
                        raise HTTPException(status_code=422, detail="Cancelled bills cannot be updated")
                    if status != "draft":
                        _reject_locked_bill_fields(data)
                    if data.get("credit_days") is not None or data.get("due_date"):
                        base_date = data.get("bill_date") or b.get("bill_date")
                        apply_credit_days_due_date(data, base_date)
                        apply_due_date_credit_days(data, base_date)
                    if line_units:
                        for ln in MOCK_PURCHASE_BILL_LINES:
                            if ln.get("id") in line_units and ln.get("bill_id") == bill_id:
                                ln["unit"] = line_units[ln["id"]] or "NOS"
                    if "lines" in data:
                        # Draft-only (guarded above via _reject_locked_bill_fields —
                        # "lines" isn't in _SOFT_BILL_UPDATE_FIELDS, so this branch is
                        # unreachable for a non-draft bill). Recompute GST + TDS with
                        # the exact same engine create uses (_compute_bill_lines_and_totals)
                        # so an edited draft can never diverge from a freshly-created one.
                        lines_data = data.pop("lines")
                        if not lines_data:
                            raise HTTPException(status_code=422, detail="At least one line item is required")
                        from routers.vendors import MOCK_VENDORS
                        vendor = next((v for v in MOCK_VENDORS if v.get("id") == b.get("vendor_id")), None) or {}
                        is_interstate = data.get("is_interstate", b.get("is_interstate", False))
                        from domain.currency.document_currency import identity_currency
                        bill_date_for_calc = data.get("bill_date") or b.get("bill_date")
                        dc = identity_currency(bill_date_for_calc)
                        computed = _compute_bill_lines_and_totals(
                            lines_data, is_interstate, vendor, bill_date_for_calc,
                            current_user.get("firm_id") or "", dc, db=None, exclude_bill_id=bill_id,
                            is_reverse_charge=bool(b.get("is_reverse_charge")),
                        )
                        MOCK_PURCHASE_BILL_LINES[:] = [ln for ln in MOCK_PURCHASE_BILL_LINES if ln.get("bill_id") != bill_id]
                        for ln in computed["computed_lines"]:
                            MOCK_PURCHASE_BILL_LINES.append({**ln, "id": str(uuid.uuid4()), "bill_id": bill_id})
                        data.update({
                            "taxable_amount_paise": computed["taxable_amount_paise"],
                            "cgst_paise":            computed["cgst_paise"],
                            "sgst_paise":            computed["sgst_paise"],
                            "igst_paise":            computed["igst_paise"],
                            "total_paise":           computed["total_paise"],
                            "total_gst_paise":       computed["total_gst_paise"],
                            "ineligible_itc_cgst_paise": computed["ineligible_itc_cgst_paise"],
                            "ineligible_itc_sgst_paise": computed["ineligible_itc_sgst_paise"],
                            "ineligible_itc_igst_paise": computed["ineligible_itc_igst_paise"],
                            "tds_paise":             computed["tds_paise"],
                            "tds_rate_bps":          computed["tds_rate_bps"],
                            "tds_section":           computed["tds_section"],
                            "tds_surcharge_paise":   computed["tds_surcharge_paise"],
                            "tds_cess_paise":        computed["tds_cess_paise"],
                            "tds_nature_of_income":  computed["tds_nature_of_income"],
                            "tds_basis":             computed["tds_basis"],
                            "tds_advance_adjusted_paise": computed["tds_advance_adjusted_paise"],
                            "tds_certificate_no": computed["tds_certificate_no"],
                            "net_payable_paise":     computed["net_payable_paise"],
                            "txn_taxable":           computed["txn_taxable"],
                            "txn_total_gst":         computed["txn_total_gst"],
                            "txn_total":             computed["txn_total"],
                            "txn_net_payable":       computed["txn_net_payable"],
                        })
                    MOCK_PURCHASE_BILLS[i] = {**b, **data, "updated_at": datetime.now(timezone.utc).isoformat()}
                    return api_response(True, MOCK_PURCHASE_BILLS[i])
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        # Tenant isolation (OOS-5): firm-scope the guard read and the write so a
        # foreign-firm bill id cannot be read or mutated under service-role.
        # select("*") — a "lines" edit needs vendor_id/is_interstate/currency
        # columns off this same row, not just status/bill_date.
        resp = db.table("purchase_bills").select("*").eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
        bill_row = resp.data[0]
        status = bill_row["status"]
        if status == "cancelled":
            raise HTTPException(status_code=422, detail="Cancelled bills cannot be updated")
        if status != "draft":
            _reject_locked_bill_fields(data)
        # FY-lock: block editing a bill dated in a locked year, and block moving it
        # INTO a locked year. (Create already validates; edits were the gap.)
        firm_id = current_user.get("firm_id") or ""
        existing_date = bill_row.get("bill_date")
        if existing_date:
            period_validation_service.validate_posting_date(firm_id, existing_date)
        if data.get("bill_date"):
            period_validation_service.validate_posting_date(firm_id, data["bill_date"])
        # Filed-return lock, same reasoning as the sales side. A purchase bill
        # inside a filed period carries ITC already claimed in that GSTR-3B.
        _client_id = resp.data[0].get("client_id")
        period_lock_service.assert_open(db, firm_id, _client_id, existing_date)
        if data.get("bill_date"):
            period_lock_service.assert_open(db, firm_id, _client_id, data["bill_date"])

        # Keep due_date and credit_days in sync whichever one was edited
        # directly (credit_days -> due_date, or due_date -> credit_days), so
        # the derived "Terms" label never goes stale relative to the actual
        # due date. Mirrors sales_invoices.py's identical update-time sync.
        if data.get("credit_days") is not None or data.get("due_date"):
            base_date = data.get("bill_date") or existing_date
            apply_credit_days_due_date(data, base_date)
            apply_due_date_credit_days(data, base_date)

        # Per-line unit correction — safe on any non-cancelled status since
        # unit never affects rate/quantity/amount/GST.
        if line_units:
            for line_id, unit in line_units.items():
                db.table("purchase_bill_lines").update(
                    {"unit": unit or "NOS"}
                ).eq("id", line_id).eq("bill_id", bill_id).execute()

        if "lines" in data:
            # Draft-only (guarded above via _reject_locked_bill_fields — "lines"
            # isn't in _SOFT_BILL_UPDATE_FIELDS, so this branch is unreachable
            # for a non-draft bill). Recompute GST + TDS with the exact same
            # engine create uses (_compute_bill_lines_and_totals) so an edited
            # draft can never diverge from a freshly-created one.
            lines_data = data.pop("lines")
            if not lines_data:
                raise HTTPException(status_code=422, detail="At least one line item is required")
            v_resp = (db.table("vendors").select("*")
                      .eq("id", bill_row.get("vendor_id")).eq("firm_id", firm_id)
                      .eq("client_id", bill_row.get("client_id")).limit(1).execute())
            if not v_resp.data:
                raise HTTPException(status_code=404, detail="Vendor not found")
            vendor = v_resp.data[0]
            is_interstate = data.get("is_interstate", bill_row.get("is_interstate", False))
            from domain.currency.document_currency import document_currency_from_row
            dc = document_currency_from_row(db, bill_row)
            computed = _compute_bill_lines_and_totals(
                lines_data, is_interstate, vendor, data.get("bill_date") or existing_date,
                firm_id, dc, db=db, exclude_bill_id=bill_id,
                is_reverse_charge=bool(bill_row.get("is_reverse_charge")),
            )
            db.table("purchase_bill_lines").delete().eq("bill_id", bill_id).execute()
            line_payloads = [
                {
                    "bill_id":               bill_id,
                    "description":           ln["description"],
                    "hsn_sac":               ln["hsn_sac"],
                    "expense_account_id":    ln.get("expense_account_id"),
                    "quantity":              ln["quantity"],
                    "unit":                  ln.get("unit") or "NOS",
                    "rate_paise":            ln["rate_paise"],
                    "gst_rate_bps":          ln["gst_rate_bps"],
                    "taxable_amount_paise":  ln["taxable_amount_paise"],
                    "cgst_paise":            ln["cgst_paise"],
                    "sgst_paise":            ln["sgst_paise"],
                    "igst_paise":            ln["igst_paise"],
                    "line_total_paise":      ln["line_total_paise"],
                    "service_catalogue_id":  ln.get("service_catalogue_id"),
                    "itc_eligible":          ln.get("itc_eligible", True),
                    "blocked_credit_reason": ln.get("blocked_credit_reason"),
                }
                for ln in computed["computed_lines"]
            ]
            db.table("purchase_bill_lines").insert(line_payloads).execute()
            data.update({
                "taxable_amount_paise": computed["taxable_amount_paise"],
                "cgst_paise":            computed["cgst_paise"],
                "sgst_paise":            computed["sgst_paise"],
                "igst_paise":            computed["igst_paise"],
                "total_paise":           computed["total_paise"],
                "total_gst_paise":       computed["total_gst_paise"],
                "ineligible_itc_cgst_paise": computed["ineligible_itc_cgst_paise"],
                "ineligible_itc_sgst_paise": computed["ineligible_itc_sgst_paise"],
                "ineligible_itc_igst_paise": computed["ineligible_itc_igst_paise"],
                "tds_paise":             computed["tds_paise"],
                "tds_rate_bps":          computed["tds_rate_bps"],
                "tds_section":           computed["tds_section"],
                "tds_surcharge_paise":   computed["tds_surcharge_paise"],
                "tds_cess_paise":        computed["tds_cess_paise"],
                "tds_nature_of_income":  computed["tds_nature_of_income"],
                "tds_basis":             computed["tds_basis"],
                "tds_advance_adjusted_paise": computed["tds_advance_adjusted_paise"],
                "tds_certificate_no": computed["tds_certificate_no"],
                "net_payable_paise":     computed["net_payable_paise"],
                "txn_taxable":           computed["txn_taxable"],
                "txn_total_gst":         computed["txn_total_gst"],
                "txn_total":             computed["txn_total"],
                "txn_net_payable":       computed["txn_net_payable"],
            })

        data["updated_at"] = datetime.now(timezone.utc).isoformat()
        upd = db.table("purchase_bills").update(data).eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).execute()
        updated = upd.data[0] if upd.data else data
        log_event(
            current_user.get("firm_id", ""), "purchase_bill", bill_id,
            "update", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=updated,
        )
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("update_purchase_bill: %s", e)
        return api_response(False, None, f"Unable to complete purchase bill operation: {e}")


def _sync_tds_register(db, firm_id: str, bill: dict) -> dict:
    """Keep tds_deductions in step with one bill, and RETURN what it found.

    Deliberately never raises: a bill that received and posted its journal
    correctly must not be rolled back because its register row could not be
    written. tds_register_service logs loudly and the row is repaired on the
    next transition of the same bill.

    The return value was previously discarded — this function was declared
    `-> None`, so the `statutory_gaps` sync_for_bill computes reached nothing
    and nothing else in the backend read them. Found by driving a client with
    foreign suppliers through a year: five gap codes were being computed and
    thrown away on every bill. Payroll's equivalent has always reached its
    caller (routers/payroll.py returns `{**run, "statutory_gaps": ...}`); this
    is the same shape for the same reason.
    """
    try:
        from services.tds_register_service import sync_for_bill
        vendor = {}
        if bill.get("vendor_id"):
            # residential_status / country_of_residence / tax_identification
            # _number decide whether this deduction belongs in 26Q or 27Q and
            # what the 27Q deductee row must carry — migration 308.
            # firm_id added here too: this read had only .eq("id", ...), which
            # is the one query shape CLAUDE.md says never to write.
            got = (db.table("vendors")
                   .select("id, name, pan, residential_status, "
                           "country_of_residence, tax_identification_number, "
                           "no_pe_declaration_on_file, no_pe_declaration_on, "
                           "no_pe_declaration_by")
                   .eq("id", bill["vendor_id"]).eq("firm_id", firm_id)
                   .limit(1).execute().data) or []
            vendor = got[0] if got else {}
        return sync_for_bill(db, firm_id, bill.get("client_id", ""), bill, vendor) or {}
    except Exception as e:                                      # noqa: BLE001
        _logger.error("TDS register sync failed for bill %s: %s", bill.get("id"), e)
        capture_soft_failure(e, operation="tds_register_sync")
    # A failed sync is reported as a synced=False result rather than silence:
    # the caller shows the CA that the register is out of step with the bill.
    return {"synced": False, "reason": "the TDS register could not be updated"}


@router.post("/{bill_id}/receive")
def receive_purchase_bill(
    bill_id: str,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """
    Transition purchase bill draft → received.
    Auto-creates journal entry via Phase2JournalService.
    IT Act §194C/194I/194J: Journal records TDS payable.
    """
    _assert_bill_scope(current_user, bill_id)
    try:
        from services.phase2_journal_service import phase2_journal_service

        if _USE_MOCK:
            for i, b in enumerate(MOCK_PURCHASE_BILLS):
                if b["id"] == bill_id:
                    if b.get("status") != "draft":
                        raise HTTPException(status_code=422, detail="Only draft bills can be received")
                    MOCK_PURCHASE_BILLS[i]["status"]      = "received"
                    MOCK_PURCHASE_BILLS[i]["received_at"] = datetime.now(timezone.utc).isoformat()
                    phase2_journal_service.journal_for_purchase_bill(
                        MOCK_PURCHASE_BILLS[i],
                        current_user.get("firm_id", ""),
                        MOCK_PURCHASE_BILLS[i]["client_id"],
                    )
                    return api_response(True, MOCK_PURCHASE_BILLS[i])
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")

        from core.supabase_client import get_supabase
        db = get_supabase()
        # Tenant isolation (OOS-5): firm-scope the guard read and the write so a
        # foreign-firm bill id cannot be read or mutated under service-role.
        resp = db.table("purchase_bills").select("*").eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).limit(1).execute()
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
        bill = resp.data[0]
        if bill.get("status") != "draft":
            raise HTTPException(status_code=422, detail="Only draft bills can be received")
        # FY-lock: receiving posts a dated journal — block if the year was locked
        # after the draft was created (deferred-posting gap).
        if bill.get("bill_date"):
            period_validation_service.validate_posting_date(current_user.get("firm_id") or "", bill["bill_date"])
            # ...and the PORTAL's lock, re-checked HERE and not only at create.
            # Receiving is what posts the journal, and it posts with the BILL's
            # date: a draft entered in March and received in June is credit
            # taken in a GSTR-3B filed in April. Checking only at create is
            # checking at the moment nothing was posted.
            period_lock_service.assert_open(
                db, current_user.get("firm_id") or "", bill.get("client_id"),
                bill["bill_date"])

        now_iso = datetime.now(timezone.utc).isoformat()
        upd = db.table("purchase_bills").update({
            "status":      "received",
            "received_at": now_iso,
        }).eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).execute()
        updated_bill = upd.data[0] if upd.data else {**bill, "status": "received"}

        # task #103: the bill above is already flipped to "received" — if the
        # journal fails to post (journal_for_purchase_bill now re-raises
        # unexpected errors instead of swallowing them; a falsy id is also
        # treated as failure), roll the status back so the bill stays a
        # re-tryable draft instead of getting stuck "received" with no GL
        # entry behind it (mirrors credit_notes.py's issue_credit_note rollback).
        try:
            journal_id = phase2_journal_service.journal_for_purchase_bill(
                bill=updated_bill,
                firm_id=current_user.get("firm_id", ""),
                client_id=updated_bill.get("client_id", ""),
            )
            if not journal_id:
                raise RuntimeError("purchase-bill journal posting returned no id")
        except Exception as jerr:
            db.table("purchase_bills").update({
                "status": "draft", "received_at": None,
            }).eq("id", bill_id).eq("firm_id", current_user.get("firm_id")).execute()
            # A deliberate business-rule rejection (e.g. period_validation_service's
            # locked-FY check inside the journal kernel) carries a real, actionable
            # status+message the CA needs — collapsing it into "Please try again" is
            # actively misleading, since retrying identical input will never succeed.
            # Only a genuinely unexpected failure gets the safe generic message.
            if isinstance(jerr, HTTPException):
                _logger.error("receive_purchase_bill: journal posting failed (HTTP %s); receipt rolled back: %s",
                               jerr.status_code, jerr.detail)
                raise
            _logger.error("receive_purchase_bill: journal posting failed; receipt rolled back: %s", jerr)
            capture_soft_failure(jerr, operation="receive_purchase_bill")
            return api_response(False, None,
                                document_failure_detail(jerr, action="receive the purchase bill"))

        # Persist the journal link so cancellation can reverse it directly.
        db.table("purchase_bills").update({"journal_entry_id": journal_id}).eq(
            "id", bill_id).eq("firm_id", current_user.get("firm_id")).execute()

        # The TDS register follows the CREDIT, which is what receiving the bill
        # is: s.194C(3) and its neighbours all say deduct at credit to the
        # payee's account or at payment, whichever is EARLIER, and a draft
        # credits nothing. Without this the deduction sat on the bill and never
        # reached the register, so there was no challan to pay by the 7th and
        # nothing to assemble 26Q from.
        _tds_sync = _sync_tds_register(db, current_user.get("firm_id", ""), updated_bill)

        log_event(
            current_user.get("firm_id", ""), "purchase_bill", bill_id,
            "status_change", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"status": "received", "journal_entry_id": journal_id},
        )
        # Record timeline event for received/posted bill
        timeline_service.log_timeline_event(
            client_id=updated_bill.get("client_id", ""),
            firm_id=current_user.get("firm_id", ""),
            financial_year=ist_fy_label(updated_bill.get("bill_date")),
            category="accounting",
            event_type="bill_posted",
            title=f"Purchase Bill {updated_bill.get('bill_no', bill_id)} posted",
            description=f"Vendor bill for ₹{updated_bill.get('total_paise', 0) // 100:,} received.",
            severity="success",
            entity_type="purchase_bill",
            entity_id=bill_id,
            amount_paise=updated_bill.get("total_paise"),
            actor_id=current_user.get("auth_user_id"),
            actor_name=current_user.get("email"),
        )

        # Inventory: stock-in + moving-average recompute for any goods lines
        # linked to a stock-tracked catalogue item, plus a reclassification
        # journal entry moving that value from the expense account it landed
        # on into Inventory. Runs AFTER the bill is committed received — a
        # failure here must never affect an already-received bill.
        # apply_purchase_to_inventory itself never raises; this try/except is
        # belt-and-suspenders.
        try:
            from domain.inventory_service import apply_purchase_to_inventory
            apply_purchase_to_inventory(
                db, firm_id=current_user.get("firm_id", ""), client_id=updated_bill.get("client_id", ""),
                # journal_entries.created_by FK references users(id), not auth_user_id.
                bill=updated_bill, created_by=current_user.get("id"),
            )
        except Exception as e:
            _logger.error("receive_purchase_bill: inventory posting failed for %s: %s", bill_id, e, exc_info=True)

        updated_bill["journal_entry_id"] = journal_id
        # The register's own account of what it wrote, and what it could not
        # establish. Carried on the receive response because THIS is the moment
        # the deduction becomes real — the credit under s.194C(3)/s.195 — and
        # the moment a CA can still act on a missing declaration or a missing
        # Form 15CA without unwinding anything.
        return api_response(True, {**updated_bill, "tds_register": _tds_sync})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("receive_purchase_bill: %s", e)
        return api_response(False, None, f"Unable to complete purchase bill operation: {e}")


@router.post("/{bill_id}/cancel")
def cancel_purchase_bill(
    bill_id: str,
    current_user: dict = Depends(rbac("accounting", "approve")),
):
    """Cancel a purchase bill. Requires accounting.approve (Partner only)."""
    _assert_bill_scope(current_user, bill_id)
    try:
        if _USE_MOCK:
            for i, b in enumerate(MOCK_PURCHASE_BILLS):
                if b["id"] == bill_id:
                    if b.get("status") == "cancelled":
                        raise HTTPException(status_code=422, detail="Bill already cancelled")
                    MOCK_PURCHASE_BILLS[i]["status"]       = "cancelled"
                    MOCK_PURCHASE_BILLS[i]["cancelled_at"] = datetime.now(timezone.utc).isoformat()
                    return api_response(True, MOCK_PURCHASE_BILLS[i])
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")

        from core.supabase_client import get_supabase
        from services.phase2_journal_service import phase2_journal_service, purchase_bill_journal_ref
        db = get_supabase()
        firm_id = current_user.get("firm_id")
        # Tenant isolation (OOS-5): firm-scope the guard read and the write so a
        # foreign-firm bill id cannot be read or mutated under service-role.
        resp = (db.table("purchase_bills")
                .select("status, journal_entry_id, bill_no, our_reference, client_id, paid_paise, debited_paise, credit_note_paise")
                .eq("id", bill_id).eq("firm_id", firm_id).limit(1).execute())
        if not resp.data:
            raise HTTPException(status_code=404, detail=f"Purchase bill {bill_id} not found")
        bill = resp.data[0]
        status = bill.get("status")
        if status == "cancelled":
            raise HTTPException(status_code=422, detail="Bill already cancelled")
        if status == "draft":
            raise HTTPException(status_code=422, detail="Draft bills are deleted, not cancelled.")
        # Accounting guard: never cancel a bill that has payments or debit/credit
        # notes applied — those journals (and, for a debit/credit note, its
        # allocation) would be stranded. Reverse/withdraw those first.
        if (int(bill.get("paid_paise") or 0) > 0 or int(bill.get("debited_paise") or 0) > 0
                or int(bill.get("credit_note_paise") or 0) > 0):
            raise HTTPException(status_code=409, detail="This bill has payments, debit notes or credit notes applied and cannot be cancelled. Reverse those first.")
        # task #102: this used to block on ANY purchase_payments row, live or
        # reversed — reverse_purchase_payment (services/reversal_service)
        # never deletes the row (audit trail), so a bill with only reversed
        # payments could never be cancelled even after every payment on it
        # was correctly undone. Filtered in Python (not .eq("is_reversed",
        # False)) so a row lacking the key — impossible on the real NOT NULL
        # DEFAULT false column, but common in older test doubles — is
        # correctly treated as live, not excluded.
        pay = (db.table("purchase_payments").select("id, is_reversed")
               .eq("firm_id", firm_id).eq("purchase_bill_id", bill_id).execute().data or [])
        if any(not p.get("is_reversed") for p in pay):
            raise HTTPException(status_code=409, detail="This bill has payments allocated and cannot be cancelled. Reverse the payment(s) first.")

        # A cancellation reversal is a NEW posting dated today — open FY required.
        reversal_date = datetime.now(timezone.utc).date().isoformat()
        period_validation_service.validate_posting_date(firm_id or "", reversal_date)

        # Locate the bill's posted receive-journal and reverse it THROUGH the kernel
        # (append-only; original untouched). Idempotent on retry.
        jrnl_id = bill.get("journal_entry_id")
        if not jrnl_id:
            # New bills post under the system-unique PB-{id} reference
            # (phase2_journal_service.purchase_bill_journal_ref); bills
            # received before that fix posted under the vendor's bill_no —
            # try both so legacy bills stay cancellable.
            for ref in (purchase_bill_journal_ref(bill_id), bill.get("bill_no")):
                if not ref:
                    continue
                jr = (db.table("journal_entries").select("id")
                      .eq("firm_id", firm_id).eq("client_id", bill.get("client_id"))
                      .eq("reference_no", ref).eq("entry_type", "Purchase").eq("is_posted", True)
                      .limit(1).execute().data)
                if jr:
                    jrnl_id = jr[0]["id"]
                    break
        if not jrnl_id:
            raise HTTPException(status_code=422, detail="No posted journal found for this bill to reverse.")
        already = (db.table("journal_entries").select("id")
                   .eq("firm_id", firm_id).eq("reversal_of", jrnl_id).limit(1).execute().data)
        if not already:
            phase2_journal_service.reverse_entry(
                db, firm_id, jrnl_id, reversal_date,
                narration=f"Cancellation of purchase bill {bill.get('bill_no') or bill_id}",
                created_by=current_user.get("id"),
            )

        upd = db.table("purchase_bills").update({
            "status":       "cancelled",
            "cancelled_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", bill_id).eq("firm_id", firm_id).execute()
        updated = upd.data[0] if upd.data else {}

        # The credit is undone, so the deduction never happened. Leaving the
        # register row would file 26Q on tax the books no longer say was
        # withheld — and would leave a challan to pay for a bill that does not
        # exist.
        _sync_tds_register(db, firm_id or "", {**bill, "id": bill_id,
                                               "status": "cancelled"})

        # Inventory: undo the stock-in + Inventory-reclass journal
        # apply_purchase_to_inventory posted at receive time, for any goods
        # lines on this bill. Runs AFTER cancellation is committed — never
        # blocks it.
        try:
            from domain.inventory_service import reverse_purchase_stock
            reverse_purchase_stock(
                db, firm_id=firm_id or "", client_id=bill.get("client_id", ""), bill_id=bill_id,
                bill_reference=bill.get("bill_no") or bill.get("our_reference") or bill_id,
                # journal_entries.created_by FK references users(id), not auth_user_id.
                created_by=current_user.get("id"),
            )
        except Exception as e:
            _logger.error("cancel_purchase_bill: inventory reversal failed for %s: %s", bill_id, e, exc_info=True)

        log_event(
            firm_id or "", "purchase_bill", bill_id,
            "cancel", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            new_data={"status": "cancelled", "reversed_journal": jrnl_id},
        )
        return api_response(True, updated)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("cancel_purchase_bill: %s", e)
        return api_response(False, None, f"Unable to complete purchase bill operation: {e}")


def _match_extracted_vendor(db, firm_id: str, client_id: str, extracted: dict):
    """The vendor an extracted invoice names, by GSTIN and then by name.

    GSTIN first because it identifies a registration; the name is a fallback
    for an unregistered supplier and is deliberately an `ilike` contains — a
    scanned bill rarely reproduces a legal name exactly. Firm- AND
    client-scoped: the service-role key bypasses RLS, and a vendor belonging
    to another client of the same firm carries the wrong TDS section, PAN and
    state code.

    Returns None when neither matches. The caller REFUSES on that; it used to
    carry the None through to the insert, against a NOT NULL column.
    """
    gstin = (extracted.get("gstin") or extracted.get("vendor_gstin") or "").strip()
    name = (extracted.get("vendor_name") or "").strip()
    if gstin:
        rows = (db.table("vendors").select("id")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .eq("gstin", gstin).limit(1).execute().data) or []
        if rows:
            return rows[0]["id"]
    if name:
        rows = (db.table("vendors").select("id")
                .eq("firm_id", firm_id).eq("client_id", client_id)
                .ilike("name", f"%{name}%").limit(1).execute().data) or []
        if rows:
            return rows[0]["id"]
    return None


def _lines_from_extraction(extracted: dict) -> list[dict]:
    """The extracted line items in `PurchaseBillLineIn`'s shape.

    The rate and the quantity are what carry over; the AMOUNTS do not, because
    `_compute_bill_lines_and_totals` derives them and is the one place that may
    (CLAUDE.md: computation lives in apps/api, once). An extracted taxable
    amount that disagrees with rate x quantity is a fact about the extraction,
    and it survives in `ai_extraction_data` for the CA to compare against.

    `gst_rate_bps` is the model's own reading of the rate; the core takes a
    percentage, so it is divided rather than re-derived from the tax heads —
    deriving it would turn two extracted figures into a third that neither the
    document nor the model ever stated.
    """
    out: list[dict] = []
    for ln in extracted.get("line_items") or []:
        out.append({
            "description": str(ln.get("description") or "").strip() or "As per supplier invoice",
            "hsn_sac": ln.get("hsn_sac") or None,
            "quantity": float(ln.get("quantity") or 1),
            "unit": ln.get("unit") or None,
            "rate_paise": int(ln.get("rate_paise") or 0),
            "gst_rate_percent": float(int(ln.get("gst_rate_bps") or 0)) / 100.0,
            # No product-catalogue awareness in an extraction, and none
            # invented: the CA links a Product/Service in the draft's editor.
            "service_catalogue_id": None,
        })
    return out


@router.post("/from-document")
def create_bill_from_document(
    data: BillFromDocumentIn,
    current_user: dict = Depends(rbac("accounting", "write")),
):
    """Create a DRAFT purchase bill from AI-extracted document data.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    Always 'draft' whatever the extraction confidence. A human calls /receive
    to post it; nothing here reaches the general ledger.

    ONE CREATE PATH (PUR-17). This used to build the bill row and its lines by
    hand and insert them itself, and it had drifted a long way from
    `_create_purchase_bill_core`:

      * a failed vendor match left `vendor_id = None` and inserted it against
        a NOT NULL column (migration 050), so the CA got
        "Unable to complete purchase bill operation" and no reason;
      * the lines went in with all three GST heads hard ZERO while the header
        carried the extracted tax, so the bill did not foot to its own lines;
      * `is_interstate`, `total_gst_paise` and the s.17(5) `ineligible_itc_*`
        columns were never set, so the bill classified wrongly in GSTR-3B and
        its blocked credit read as claimable;
      * TDS was a hard zero under a comment saying it "requires CA review",
        which the ordinary create path does not do and CLAUDE.md forbids —
        the rate is the engine's, and the bill is a draft either way; and
      * neither the financial-year lock nor the filed-return lock was checked,
        so an extraction could book a bill into a period a return had closed.

    Now it resolves the vendor, maps the extraction into the core's own input
    shape and calls the core. What the extraction cannot supply is REFUSED and
    named rather than filled in: no vendor match and no line items are both
    422s that say what to do.

    ONE DIVERGENCE SURVIVES, DELIBERATELY. The core is handed plain dicts, not
    `PurchaseBillLineIn`, so the model's "Product/Service is required on every
    line" validator does not run — an extraction has no product-catalogue
    awareness and inventing a link would be worse than leaving it. A line with
    no `service_catalogue_id` simply moves no stock
    (`inventory_service.apply_purchase_to_inventory` skips it and returns), and
    the CA links the item in the draft's line editor before /receive. Do not
    "tidy" these into the model: it would refuse every extracted bill.
    """
    assert_client_access(current_user, data.client_id)
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    try:
        client_id      = data.client_id
        extracted_data = data.extracted_data
        firm_id        = current_user.get("firm_id")

        if not client_id:
            raise HTTPException(status_code=422, detail="client_id is required")
        if not extracted_data:
            raise HTTPException(status_code=422, detail="extracted_data is required")

        if _USE_MOCK:
            from routers.vendors import MOCK_VENDORS
            gstin = (extracted_data.get("gstin")
                     or extracted_data.get("vendor_gstin") or "").strip()
            name = (extracted_data.get("vendor_name") or "").strip().lower()
            vendor_id = next(
                (v["id"] for v in MOCK_VENDORS
                 if (gstin and v.get("gstin") == gstin)
                 or (name and name in str(v.get("name", "")).lower())), None)
        else:
            from core.supabase_client import get_supabase
            vendor_id = _match_extracted_vendor(
                get_supabase(), firm_id or "", client_id, extracted_data)

        if not vendor_id:
            raise HTTPException(status_code=422, detail=(
                "No vendor on this client's books matches the supplier on this "
                "document. Add the supplier as a vendor and upload again, or "
                "enter the bill directly. A bill cannot be booked without one: "
                "the vendor carries the TDS section, PAN and state code the "
                "bill is computed from."))

        lines = _lines_from_extraction(extracted_data)
        if not lines:
            raise HTTPException(status_code=422, detail=(
                "No line items were read from this document. A purchase bill "
                "needs at least one line — GST is charged per line at the "
                "line's own rate. Enter the bill directly, or re-upload a "
                "clearer scan."))

        bill = _create_purchase_bill_core({
            "client_id":          client_id,
            "vendor_id":          vendor_id,
            "bill_no":            extracted_data.get("invoice_no", ""),
            "bill_date":          extracted_data.get("invoice_date", ""),
            "lines":              lines,
            "is_ai_extracted":    True,
            "ai_extraction_data": extracted_data,
        }, current_user)

        # Separate audit event for document_extraction — tracks AI extraction
        # usage. The core writes the ordinary "create" event already.
        log_event(
            firm_id or "", "purchase_bill", bill.get("id"),
            "document_extraction", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"),
            metadata={
                "vendor_gstin": extracted_data.get("vendor_gstin"),
                "invoice_no":   extracted_data.get("invoice_no"),
                "requires_review": True,
            },
        )
        return api_response(True, {**bill, "requires_review": True})
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("create_bill_from_document: %s", e)
        return api_response(False, None, f"Unable to complete purchase bill operation: {e}")
