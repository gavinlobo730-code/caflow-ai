"""GST Engine API router.

Endpoints for GSTR-1/3B computation, validation, CA approval, and JSON download.
All computation is pure Python — no external dependencies.
Data is passed in from frontend (which reads Supabase directly).

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to any government portal.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access
from domain.gst.classifier import (
    TransactionForClassification,
    classify_transactions,
    GSTInvoiceCategory,
)
from domain.gst.gstr3b_computer import (
    SalesTransaction,
    PurchaseTransaction,
    GSTR2ARecord,
    compute_gstr3b,
)
from domain.gst.gstr1_builder import (
    InvoiceForGSTR1,
    InvoiceLine,
    build_gstr1,
)
from domain.gst.validator import GSTValidator, InvoiceToValidate
from services import gst_return_service

router = APIRouter(prefix="/api/gst", tags=["gst"])

# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# This router imported no authz. Only `FromBooksRequest` carries a client_id,
# and both endpoints that take one read a client's posted invoices, credit
# notes and GL control accounts straight out of the ledger — and resolve the
# client's own GSTIN on the way.
#
# The other five endpoints are exempt and stay that way: /classify, /gstr1/build,
# /gstr3b/compute and the two /validate endpoints are pure functions over rows
# the caller supplied in the request, and their models have NO client_id at all.
# That is a stronger exemption than the TDS /compute pair had, where the field
# existed and was merely unused — here there is nothing to check.

_validator = GSTValidator()


# ── Request / Response Models ─────────────────────────────────────────────────

class TransactionClassifyRequest(BaseModel):
    transactions: list[dict] = Field(
        description="List of transaction records from Supabase transactions table"
    )


class ClassifyResponse(BaseModel):
    results: dict[str, str]   # transaction_id → category
    counts: dict[str, int]


class GSTR3BRequest(BaseModel):
    gstin: str
    period: str  # MMYYYY
    sales: list[dict] = Field(description="Posted sales invoices for the period")
    purchases: list[dict] = Field(description="Posted purchase invoices for the period")
    gstr2a_records: list[dict] = Field(default=[], description="GSTR-2A records for the period")


class GSTR1Request(BaseModel):
    gstin: str
    period: str  # MMYYYY
    invoices: list[dict] = Field(
        description="Classified posted transactions for the period"
    )
    invoice_lines: dict[str, list[dict]] = Field(
        default={},
        description="Map of transaction_id → list of transaction_line records"
    )
    aggregate_turnover_paise: int = Field(
        default=0,
        description="Annual aggregate turnover for HSN digit requirement"
    )


class ValidateGSTR1Request(BaseModel):
    gstin: str
    period: str
    invoices: list[dict]


class ValidateGSTR3BRequest(BaseModel):
    gstin: str
    period: str
    output_igst: int
    output_cgst: int
    output_sgst: int
    itc_igst: int
    itc_cgst: int
    itc_sgst: int


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_sales(rows: list[dict]) -> list[SalesTransaction]:
    return [
        SalesTransaction(
            transaction_type=r.get("transaction_type", "sales_invoice"),
            taxable_amount_paise=int(r.get("taxable_amount_paise", 0)),
            cgst_paise=int(r.get("cgst_paise", 0)),
            sgst_paise=int(r.get("sgst_paise", 0)),
            igst_paise=int(r.get("igst_paise", 0)),
            cess_paise=int(r.get("cess_paise", 0)),
            supply_type=r.get("supply_type", "taxable"),
            is_reverse_charge=bool(r.get("is_reverse_charge", False)),
        )
        for r in rows
    ]


def _parse_purchases(rows: list[dict]) -> list[PurchaseTransaction]:
    return [
        PurchaseTransaction(
            taxable_amount_paise=int(r.get("taxable_amount_paise", 0)),
            cgst_paise=int(r.get("cgst_paise", 0)),
            sgst_paise=int(r.get("sgst_paise", 0)),
            igst_paise=int(r.get("igst_paise", 0)),
            cess_paise=int(r.get("cess_paise", 0)),
            is_reverse_charge=bool(r.get("is_reverse_charge", False)),
        )
        for r in rows
    ]


def _parse_gstr2a(rows: list[dict]) -> list[GSTR2ARecord]:
    return [
        GSTR2ARecord(
            cgst_paise=int(r.get("cgst_paise", 0)),
            sgst_paise=int(r.get("sgst_paise", 0)),
            igst_paise=int(r.get("igst_paise", 0)),
        )
        for r in rows
    ]


def _parse_invoice_line(r: dict) -> InvoiceLine:
    return InvoiceLine(
        hsn_sac_code=r.get("hsn_sac_code") or "",
        description=r.get("description") or "",
        quantity=float(r.get("quantity", 1)),
        unit=r.get("unit") or "NOS",
        rate_paise=int(r.get("rate_paise", 0)),
        taxable_paise=int(r.get("taxable_paise", 0)),
        gst_rate=float(r.get("gst_rate", 0)),
        cgst_paise=int(r.get("cgst_paise", 0)),
        sgst_paise=int(r.get("sgst_paise", 0)),
        igst_paise=int(r.get("igst_paise", 0)),
        cess_paise=int(r.get("cess_paise", 0)),
    )


def _parse_invoices_for_gstr1(
    rows: list[dict],
    lines_map: dict[str, list[dict]],
) -> list[InvoiceForGSTR1]:
    result = []
    for r in rows:
        txn_id = r.get("id", "")
        raw_lines = lines_map.get(txn_id, [])
        category_str = r.get("gst_invoice_category")
        if not category_str:
            # Auto-classify if not already set
            txn_for_classify = TransactionForClassification(
                id=txn_id,
                transaction_type=r.get("transaction_type", "sales_invoice"),
                party_gstin=r.get("party_gstin"),
                is_interstate=bool(r.get("is_interstate", False)),
                taxable_amount_paise=int(r.get("taxable_amount_paise", 0)),
                supply_type=r.get("supply_type", "taxable"),
                invoice_type=r.get("invoice_type", "Regular"),
                place_of_supply=r.get("place_of_supply"),
                invoice_value_paise=(int(r.get("taxable_amount_paise", 0) or 0)
                                     + int(r.get("cgst_paise", 0) or 0)
                                     + int(r.get("sgst_paise", 0) or 0)
                                     + int(r.get("igst_paise", 0) or 0)
                                     + int(r.get("cess_paise", 0) or 0)
                                     + int(r.get("round_off_paise", 0) or 0)),
                transaction_date=r.get("transaction_date"),
            )
            from domain.gst.classifier import classify_transaction
            category = classify_transaction(txn_for_classify)
        else:
            try:
                category = GSTInvoiceCategory(category_str)
            except ValueError:
                category = GSTInvoiceCategory.B2CS

        result.append(InvoiceForGSTR1(
            id=txn_id,
            transaction_type=r.get("transaction_type", "sales_invoice"),
            reference_no=r.get("reference_no") or r.get("id", ""),
            transaction_date=r.get("transaction_date", ""),
            party_gstin=r.get("party_gstin"),
            party_name=r.get("party_name") or "",
            place_of_supply=r.get("place_of_supply") or "",
            is_interstate=bool(r.get("is_interstate", False)),
            taxable_amount_paise=int(r.get("taxable_amount_paise", 0)),
            cgst_paise=int(r.get("cgst_paise", 0)),
            sgst_paise=int(r.get("sgst_paise", 0)),
            igst_paise=int(r.get("igst_paise", 0)),
            cess_paise=int(r.get("cess_paise", 0)),
            round_off_paise=int(r.get("round_off_paise", 0) or 0),
            is_reverse_charge=bool(r.get("is_reverse_charge", False)),
            invoice_type=r.get("invoice_type", "Regular"),
            supply_type=r.get("supply_type", "taxable"),
            gst_invoice_category=category,
            original_invoice_ref=r.get("original_invoice_ref"),
            original_invoice_date=r.get("original_invoice_date"),
            lines=[_parse_invoice_line(l) for l in raw_lines],
        ))
    return result


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/classify")
def classify_invoices(req: TransactionClassifyRequest, current_user: dict = Depends(rbac("gst", "compute"))):
    """Classify transactions into GSTN invoice categories.

    Returns classification for each transaction_id.
    Frontend should persist gst_invoice_category back to Supabase.
    """
    txns = [
        TransactionForClassification(
            id=r.get("id", ""),
            transaction_type=r.get("transaction_type", "sales_invoice"),
            party_gstin=r.get("party_gstin"),
            is_interstate=bool(r.get("is_interstate", False)),
            taxable_amount_paise=int(r.get("taxable_amount_paise", 0)),
            supply_type=r.get("supply_type", "taxable"),
            invoice_type=r.get("invoice_type", "Regular"),
            place_of_supply=r.get("place_of_supply"),
            invoice_value_paise=(int(r.get("taxable_amount_paise", 0) or 0)
                             + int(r.get("cgst_paise", 0) or 0)
                             + int(r.get("sgst_paise", 0) or 0)
                             + int(r.get("igst_paise", 0) or 0)
                             + int(r.get("cess_paise", 0) or 0)
                             + int(r.get("round_off_paise", 0) or 0)),
            transaction_date=r.get("transaction_date"),
        )
        for r in req.transactions
    ]
    results = classify_transactions(txns)
    counts: dict[str, int] = {}
    for cat in results.values():
        counts[cat.value] = counts.get(cat.value, 0) + 1

    return api_response(True, {
        "results": {k: v.value for k, v in results.items()},
        "counts": counts,
        "total": len(results),
    })


@router.post("/gstr3b/compute")
def compute_gstr3b_endpoint(req: GSTR3BRequest, current_user: dict = Depends(rbac("gst", "compute"))):
    """Compute GSTR-3B figures from transaction data.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    Returns computed payload ready for GSTN portal upload after CA review.
    """
    validation_errors = _validator.validate_gstin(req.gstin)
    validation_errors += _validator.validate_period(req.period)
    if validation_errors:
        raise HTTPException(
            status_code=422,
            detail={"validation_errors": [e.as_dict() for e in validation_errors]},
        )

    sales = _parse_sales(req.sales)
    purchases = _parse_purchases(req.purchases)
    gstr2a = _parse_gstr2a(req.gstr2a_records)

    result = compute_gstr3b(sales, purchases, gstr2a)

    gstr3b_validation = _validator.validate_gstr3b(
        gstin=req.gstin,
        period=req.period,
        output_igst=result.outward_taxable_igst,
        output_cgst=result.outward_taxable_cgst,
        output_sgst=result.outward_taxable_sgst,
        itc_igst=result.itc_igst,
        itc_cgst=result.itc_cgst,
        itc_sgst=result.itc_sgst,
    )

    return api_response(True, {
        "payload": result.as_gstn_payload(req.gstin, req.period),
        "working": {
            "outward": {
                "taxable_igst_paise": result.outward_taxable_igst,
                "taxable_cgst_paise": result.outward_taxable_cgst,
                "taxable_sgst_paise": result.outward_taxable_sgst,
                "zero_rated_paise": result.outward_zero_rated,
                "nil_exempt_paise": result.outward_nil_exempt,
            },
            "itc": {
                "book_igst_paise": result.itc_book_igst,
                "book_cgst_paise": result.itc_book_cgst,
                "book_sgst_paise": result.itc_book_sgst,
                "gstr2a_igst_paise": result.itc_2a_igst,
                "gstr2a_cgst_paise": result.itc_2a_cgst,
                "gstr2a_sgst_paise": result.itc_2a_sgst,
                "eligible_igst_paise": result.itc_igst,
                "eligible_cgst_paise": result.itc_cgst,
                "eligible_sgst_paise": result.itc_sgst,
                "rule_36_4_cap_applied": result.itc_capped_by_2a,
            },
            "net_payable": {
                "igst_paise": result.net_igst,
                "cgst_paise": result.net_cgst,
                "sgst_paise": result.net_sgst,
                "total_paise": result.net_igst + result.net_cgst + result.net_sgst,
            },
        },
        "validation_warnings": [e.as_dict() for e in gstr3b_validation],
        "period": req.period,
        "gstin": req.gstin,
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        "ca_review_required": True,
    })


class FromBooksRequest(BaseModel):
    client_id: str
    period: str  # MMYYYY
    aggregate_turnover_paise: int = 0


def _client_gstin(db, firm_id: str, client_id: str) -> str:
    """Fetch the client's GSTIN, firm-scoped. Raises 404 if the client isn't ours."""
    row = (db.table("clients").select("gstin")
           .eq("id", client_id).eq("firm_id", firm_id).limit(1).execute().data)
    if not row:
        raise HTTPException(status_code=404, detail="Client not found")
    return (row[0].get("gstin") or "").strip()


@router.post("/gstr3b/from-books")
def gstr3b_from_books_endpoint(req: FromBooksRequest, current_user: dict = Depends(rbac("gst", "compute"))):
    """Compute GSTR-3B ENTIRELY from posted accounting data and reconcile it to the
    General Ledger — the single source of truth (audit H8). Returns a reconciliation
    block proving the return's output tax and ITC equal the GL GST control accounts.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    # Before the database is touched at all, let alone the client's ledger.
    assert_client_access(current_user, req.client_id)
    from core.supabase_client import get_supabase
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    gstin = _client_gstin(db, firm_id, req.client_id)
    errs = _validator.validate_gstin(gstin) + _validator.validate_period(req.period)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": [e.as_dict() for e in errs]})
    try:
        data = gst_return_service.gstr3b_from_books(db, firm_id, req.client_id, req.period, gstin)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    return api_response(True, data)


@router.get("/gstr3b/detail")
def gstr3b_detail_endpoint(
    client_id: str = Query(...),
    period: str = Query(..., description="MMYYYY e.g. 042026"),
    line: str = Query(..., description="One of 3.1a, 4A, 4B1, 4B2"),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """The documents behind one GSTR-3B figure — the detail half of the return.

    GSTR-1 has had this since it shipped (B2B/B2CS/B2CL/HSN, invoice by invoice).
    GSTR-3B had nothing: a CA could see ITC of Rs 54,32,625.99 with no way to ask
    which bills that was. The summary is what gets filed; this is what gets
    checked before filing.

    Reads the SAME fetchers gstr3b_from_books uses, so the detail and the summary
    cannot disagree, and returns its own totals so the screen can print both.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    assert_client_access(current_user, client_id)
    from core.supabase_client import get_supabase
    db = get_supabase()
    errs = _validator.validate_period(period)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": [e.as_dict() for e in errs]})
    try:
        data = gst_return_service.gstr3b_detail(
            db, current_user.get("firm_id"), client_id, period, line)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    return api_response(True, data)


@router.post("/gstr1/from-books")
def gstr1_from_books_endpoint(req: FromBooksRequest, current_user: dict = Depends(rbac("gst", "compute"))):
    """Build GSTR-1 ENTIRELY from posted sales invoices + issued credit notes and
    reconcile the net output tax to the General Ledger (audit H8).

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    # Before the database is touched at all, let alone the client's ledger.
    assert_client_access(current_user, req.client_id)
    from core.supabase_client import get_supabase
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    gstin = _client_gstin(db, firm_id, req.client_id)
    errs = _validator.validate_gstin(gstin) + _validator.validate_period(req.period)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": [e.as_dict() for e in errs]})
    try:
        data = gst_return_service.gstr1_from_books(
            db, firm_id, req.client_id, req.period, gstin, req.aggregate_turnover_paise)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    return api_response(True, data)


@router.post("/gstr1/with-amendments")
def gstr1_with_amendments_endpoint(req: FromBooksRequest, current_user: dict = Depends(rbac("gst", "compute"))):
    """GSTR-1 from books, with the amendment tables this period has to carry.

    CGST Act §37: a filed GSTR-1 can never be revised, so a correction to an
    earlier period is declared in a LATER return's amendment tables — 9A for
    invoices, 9C for notes, 10 for B2C-others. services/gst_amendment_service
    has worked out which corrections are outstanding since it was built, and
    domain/gst/amendments.merge_into_payload has been able to fold them into a
    payload for just as long. NOTHING CONNECTED THE TWO: there was no route
    that produced the merged payload, so a CA could see the amendments and had
    no way to file them.

    Out-of-time corrections are already excluded upstream — outstanding_
    amendments only collects entries for a period whose §37(3) window is still
    open — so nothing here can declare an amendment that the law no longer
    allows. Amounts the CA must decide on (a document cancelled after filing)
    and invoices that were never declared at all stay OUT of the payload and
    are returned alongside it, because neither is an amendment.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT. This produces a file; uploading
    # it to gst.gov.in remains a deliberate human act.
    """
    assert_client_access(current_user, req.client_id)
    from core.supabase_client import get_supabase
    db = get_supabase()
    firm_id = current_user.get("firm_id")
    gstin = _client_gstin(db, firm_id, req.client_id)
    errs = _validator.validate_gstin(gstin) + _validator.validate_period(req.period)
    if errs:
        raise HTTPException(status_code=422, detail={"validation_errors": [e.as_dict() for e in errs]})
    from services.gst_amendment_service import apply_amendments, outstanding_amendments
    try:
        base = gst_return_service.gstr1_from_books(
            db, firm_id, req.client_id, req.period, gstin, req.aggregate_turnover_paise)
    except ValueError as ve:
        raise HTTPException(status_code=422, detail=str(ve))
    outstanding = outstanding_amendments(db, firm_id, req.client_id, req.period)
    return api_response(True, {
        **base,
        "payload": apply_amendments(base["payload"], outstanding),
        "amendments": {
            "sections": sorted((outstanding.get("sections") or {}).keys()),
            "counts": outstanding.get("counts") or {},
            "source_periods": outstanding.get("source_periods") or [],
            "expired": outstanding.get("expired") or [],
            "needs_decision": outstanding.get("needs_decision") or [],
            "carry_forward": outstanding.get("carry_forward") or [],
            "closing_soon": outstanding.get("closing_soon") or [],
        },
        "ca_review_required": True,   # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    })


@router.post("/gstr1/build")
def build_gstr1_endpoint(req: GSTR1Request, current_user: dict = Depends(rbac("gst", "compute"))):
    """Build GSTR-1 JSON payload from classified transaction data.

    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    """
    validation_errors = _validator.validate_gstin(req.gstin)
    validation_errors += _validator.validate_period(req.period)
    if validation_errors:
        raise HTTPException(
            status_code=422,
            detail={"validation_errors": [e.as_dict() for e in validation_errors]},
        )

    invoices = _parse_invoices_for_gstr1(req.invoices, req.invoice_lines)

    # Validate all invoices
    invoices_to_validate = [
        InvoiceToValidate(
            reference_no=inv.reference_no,
            transaction_date=inv.transaction_date,
            party_gstin=inv.party_gstin,
            place_of_supply=inv.place_of_supply,
            taxable_amount_paise=inv.taxable_amount_paise,
            cgst_paise=inv.cgst_paise,
            sgst_paise=inv.sgst_paise,
            igst_paise=inv.igst_paise,
            is_interstate=inv.is_interstate,
            gst_rate=None,
        )
        for inv in invoices
    ]
    validation_errors_inv = _validator.validate_gstr1(req.gstin, req.period, invoices_to_validate)

    payload = build_gstr1(invoices, req.gstin, req.period, req.aggregate_turnover_paise)

    return api_response(True, {
        "payload": payload.payload,
        "summary": payload.summary,
        "invoice_count": payload.invoice_count,
        "taxable_total_rupees": payload.taxable_total_paise / 100,
        "tax_total_rupees": payload.tax_total_paise / 100,
        "validation_errors": [e.as_dict() for e in validation_errors_inv if e.severity == "error"],
        "validation_warnings": [e.as_dict() for e in validation_errors_inv if e.severity == "warning"],
        "period": req.period,
        "gstin": req.gstin,
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        "ca_review_required": True,
    })


@router.post("/validate/gstr1")
def validate_gstr1_endpoint(req: ValidateGSTR1Request, current_user: dict = Depends(rbac("gst", "read"))):
    """Validate GSTR-1 invoice data without building the full payload."""
    invoices_to_validate = [
        InvoiceToValidate(
            reference_no=r.get("reference_no") or "",
            transaction_date=r.get("transaction_date", ""),
            party_gstin=r.get("party_gstin"),
            place_of_supply=r.get("place_of_supply"),
            taxable_amount_paise=int(r.get("taxable_amount_paise", 0)),
            cgst_paise=int(r.get("cgst_paise", 0)),
            sgst_paise=int(r.get("sgst_paise", 0)),
            igst_paise=int(r.get("igst_paise", 0)),
            is_interstate=bool(r.get("is_interstate", False)),
            gst_rate=r.get("gst_rate"),
        )
        for r in req.invoices
    ]
    errors = _validator.validate_gstr1(req.gstin, req.period, invoices_to_validate)
    return api_response(True, {
        "valid": not any(e.severity == "error" for e in errors),
        "errors": [e.as_dict() for e in errors if e.severity == "error"],
        "warnings": [e.as_dict() for e in errors if e.severity == "warning"],
        "total_invoices": len(req.invoices),
    })


@router.post("/validate/gstr3b")
def validate_gstr3b_endpoint(req: ValidateGSTR3BRequest, current_user: dict = Depends(rbac("gst", "read"))):
    """Validate GSTR-3B figures for internal consistency."""
    errors = _validator.validate_gstr3b(
        gstin=req.gstin,
        period=req.period,
        output_igst=req.output_igst,
        output_cgst=req.output_cgst,
        output_sgst=req.output_sgst,
        itc_igst=req.itc_igst,
        itc_cgst=req.itc_cgst,
        itc_sgst=req.itc_sgst,
    )
    return api_response(True, {
        "valid": not any(e.severity == "error" for e in errors),
        "errors": [e.as_dict() for e in errors if e.severity == "error"],
        "warnings": [e.as_dict() for e in errors if e.severity == "warning"],
    })
