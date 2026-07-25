"""
TDS Workspace router — challan management, returns, certificates, 26AS reconciliation.

IT Act §192-194Q (TDS sections), §203 (Form 16/16A certificates).
All monetary amounts in integer paise — never float.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or any government portal.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access
from domain.tds.tds_validator import TDSValidator
from services.audit_service import log_event
from services.timeline_service import timeline_service
from services.period_validation_service import period_validation_service

router = APIRouter(prefix="/api/tds-workspace", tags=["tds_workspace"])
_logger = logging.getLogger("caflow.tds_workspace")

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# ── Mock stores ───────────────────────────────────────────────────────────────
_MOCK_CHALLANS: dict[str, dict] = {}
_MOCK_RETURNS: dict[str, dict] = {}
_MOCK_CERTIFICATES: dict[str, dict] = {}
_MOCK_FORM26AS: dict[str, dict] = {}
_MOCK_DEDUCTIONS: dict[str, dict] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _tds_return_due_date(quarter: str, fy: str) -> str:
    """24Q/26Q filing due date per IT Rules Rule 31A: Q1 → 31 Jul, Q2 → 31 Oct,
    Q3 → 31 Jan, Q4 → 31 May. F17 fix: this used to compute Q4 as
    "{fy_start_year}-04-31" — a date that does not exist (April has 30 days),
    in the wrong month (Rule 31A gives Q4 until 31 May, not "the month after
    quarter end" like Q1-Q3) and the wrong year (the FY's START year instead
    of the year Q4 actually ends in). Delegates to the shared FY-aware
    calendar in domain/tds/section_rates.py."""
    from domain.tds.section_rates import quarter_dates
    try:
        return quarter_dates(fy, quarter)[2]
    except ValueError:
        return quarter_dates(fy, "Q1")[2]  # preserve old .get(quarter, Q1) fallback


# ── Request Models ─────────────────────────────────────────────────────────────

class CreateChallanRequest(BaseModel):
    client_id: str
    bsr_code: str = Field(..., description="7-digit BSR code of bank branch")
    challan_date: str = Field(..., description="YYYY-MM-DD")
    amount_paise: int = Field(..., description="Integer paise only")
    challan_no: str
    section: str = Field(..., description="e.g. 194A, 192, 194Q")
    financial_year: str = Field(..., description="e.g. 2025-26")
    quarter: str = Field(..., description="Q1, Q2, Q3, Q4")


class CreateReturnRequest(BaseModel):
    client_id: str
    return_type: str = Field(..., description="24Q or 26Q")
    quarter: str
    financial_year: str
    deductee_details: list[dict] = Field(default_factory=list)
    # Populated when saving a "Compute from Books" result (services/
    # tds_return_service.py) — optional so the existing quick-create form
    # (which never supplies these) keeps working unchanged.
    total_deductions_paise: Optional[int] = None
    total_deposits_paise: Optional[int] = None
    deductee_count: Optional[int] = None
    validation_errors: Optional[list[str]] = None


class UpdateReturnStatusRequest(BaseModel):
    status: str
    ca_approved: bool = False
    # Government proof-of-filing — required to actually transition to "filed"
    # (migration 037: tds_returns.prn/ack_number/filed_at). Previously this
    # endpoint only ever wrote `status`, so a CA could mark a return "filed"
    # with no PRN/acknowledgement captured anywhere server-side.
    prn: Optional[str] = None
    ack_number: Optional[str] = None
    filing_date: Optional[str] = None


class CreateCertificateRequest(BaseModel):
    client_id: str
    deductee_pan: str
    deductee_name: str
    financial_year: str
    certificate_type: str = Field(..., description="Form 16 or Form 16A")
    tds_amount_paise: int = Field(default=0, description="Integer paise only")
    section: str


class Form26ASUploadRequest(BaseModel):
    client_id: str
    financial_year: str
    file_url: Optional[str] = None
    raw_data: dict = Field(default_factory=dict)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
def tds_dashboard(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("tds", "read")),
):
    """TDS filing dashboard — summary of deductions, challans, returns."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            challans = [c for c in _MOCK_CHALLANS.values() if c["client_id"] == client_id]
            returns = [r for r in _MOCK_RETURNS.values() if r["client_id"] == client_id]
            certs = [c for c in _MOCK_CERTIFICATES.values() if c["client_id"] == client_id]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            challans = sb.table("tds_challans").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
            returns = sb.table("tds_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
            certs = sb.table("tds_certificates").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []

        # tds_challans has no amount_paise column (migration 037) — total_paise
        # is the real grand-total column.
        total_deposited_paise = sum(c.get("total_paise", 0) for c in challans)
        return api_response(True, {
            "challans": challans,
            "returns": returns,
            "certificates": certs,
            "summary": {
                "total_challans": len(challans),
                "total_returns": len(returns),
                "total_certificates": len(certs),
                "total_deposited_paise": total_deposited_paise,
            },
        })
    except Exception as e:
        _logger.exception("tds_dashboard error")
        return api_response(False, None, str(e))


@router.get("/deductions")
def list_deductions(
    client_id: str = Query(...),
    quarter: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("tds", "read")),
):
    """List TDS deductions for client. IT Act §192-194Q."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [d for d in _MOCK_DEDUCTIONS.values() if d["client_id"] == client_id]
            if quarter:
                rows = [d for d in rows if d.get("quarter") == quarter]
            rows = rows[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            q = sb.table("tds_deductions").select("*").eq("firm_id", firm_id).eq("client_id", client_id)
            if quarter:
                q = q.eq("quarter", quarter)
            rows = q.range(offset, offset + limit - 1).execute().data or []

        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/challans")
def list_challans(
    client_id: str = Query(...),
    from_date: Optional[str] = Query(None, description="Filter by payment_date >= from_date (YYYY-MM-DD)"),
    to_date: Optional[str] = Query(None, description="Filter by payment_date <= to_date (YYYY-MM-DD)"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("tds", "read")),
):
    """List TDS challans for client."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [c for c in _MOCK_CHALLANS.values() if c["client_id"] == client_id]
            if from_date:
                rows = [r for r in rows if r.get("payment_date", "") >= from_date]
            if to_date:
                rows = [r for r in rows if r.get("payment_date", "") <= to_date]
            rows = rows[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            # tds_challans has no challan_date column (migration 037) — payment_date
            # is the real date column.
            q = get_supabase().table("tds_challans").select("*").eq("firm_id", firm_id).eq("client_id", client_id)
            if from_date:
                q = q.gte("payment_date", from_date)
            if to_date:
                q = q.lte("payment_date", to_date)
            rows = q.range(offset, offset + limit - 1).execute().data or []
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/challans")
def create_challan(
    body: CreateChallanRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """Create TDS challan record. IT Act §200."""
    try:
        assert_client_access(current_user, body.client_id)
        firm_id = current_user["firm_id"]
        # Period validation — prevent posting to locked financial years (migration 020)
        period_validation_service.validate_posting_date(firm_id or "", body.challan_date)
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "bsr_code": body.bsr_code,
            # tds_challans has no challan_date/amount_paise columns (migration
            # 037) — payment_date is the real date column, and with no
            # surcharge/interest/penalty breakout on this quick-create form
            # the full amount is booked as pure TDS (tds_paise == total_paise).
            "payment_date": body.challan_date,
            "tds_paise": body.amount_paise,
            "total_paise": body.amount_paise,
            "challan_no": body.challan_no,
            "section": body.section,
            "financial_year": body.financial_year,
            "quarter": body.quarter,
            "status": "deposited",
            "created_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_CHALLANS[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("tds_challans").insert(record).execute()

        log_event(firm_id, "tds_challan", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        timeline_service.log_timeline_event(
            client_id=body.client_id, firm_id=firm_id,
            financial_year=body.financial_year, category="tds",
            event_type="tds_challan_deposited",
            title=f"TDS Challan deposited: ₹{body.amount_paise // 100} under {body.section}",
        )
        return api_response(True, record)
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/challans/{challan_id}")
def get_challan(challan_id: str, current_user: dict = Depends(rbac("tds", "read"))):
    """Get TDS challan by ID."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rec = _MOCK_CHALLANS.get(challan_id)
            if not rec:
                return api_response(False, None, "Not found")
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("tds_challans").select("*").eq("id", challan_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else None
            if not rec:
                return api_response(False, None, "Not found")
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/returns")
def list_returns(
    client_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("tds", "read")),
):
    """List TDS returns for client."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [r for r in _MOCK_RETURNS.values() if r["client_id"] == client_id]
            rows = rows[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("tds_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).range(offset, offset + limit - 1).execute().data or []
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/returns")
def create_return(
    body: CreateReturnRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """Create/save TDS return (24Q/26Q). IT Act §200."""
    try:
        assert_client_access(current_user, body.client_id)
        firm_id = current_user["firm_id"]
        # Validate that the FY is not locked — use April 1 of the FY start year
        fy_str = body.financial_year or ""
        if fy_str and len(fy_str) >= 4:
            fy_start_year = int(fy_str[:4])
            fy_start_date = f"{fy_start_year}-04-01"
            period_validation_service.validate_posting_date(firm_id or "", fy_start_date)
        # IT Act §206AA: PAN sentinels ("PANNOTAVBL"/"PANAPPLIED") are valid —
        # same rule domain/tds/tds_computer.py enforces for return computation.
        for d in body.deductee_details:
            pan = d.get("deductee_pan")
            if pan and not TDSValidator.validate_pan(str(pan).strip().upper()):
                raise HTTPException(status_code=422,
                                    detail=f"Invalid deductee PAN format: '{pan}'. "
                                           "Expected: AAAAA9999A, or PANNOTAVBL/PANAPPLIED if unavailable.")
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "return_type": body.return_type,
            "quarter": body.quarter,
            "financial_year": body.financial_year,
            "status": "pending",
            "due_date": _tds_return_due_date(body.quarter, body.financial_year),
            "created_at": datetime.utcnow().isoformat(),
        }
        # tds_returns has no deductee_details column (migration 037) — fvu_json
        # is the real holder for deductee-level detail. Only set it when the
        # caller actually supplied rows (this quick-create form never does).
        if body.deductee_details:
            record["fvu_json"] = {"deductees": body.deductee_details}
        # Only ever set by the "Compute from Books" flow (services/
        # tds_return_service.py) — the quick-create form leaves these columns
        # at their DB default (0/NULL) since it has no computed figures yet.
        if body.total_deductions_paise is not None:
            record["total_deductions_paise"] = body.total_deductions_paise
        if body.total_deposits_paise is not None:
            record["total_deposits_paise"] = body.total_deposits_paise
        if body.deductee_count is not None:
            record["deductee_count"] = body.deductee_count
        if body.validation_errors is not None:
            record["validation_errors"] = body.validation_errors

        if _USE_MOCK:
            _MOCK_RETURNS[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("tds_returns").insert(record).execute()

        log_event(firm_id, "tds_return", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        return api_response(True, record)
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, str(e))


@router.patch("/returns/{return_id}/status")
def update_return_status(
    return_id: str,
    body: UpdateReturnStatusRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """
    Update TDS return status: pending → prepared → ca_approved → filed.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES.
    """
    try:
        firm_id = current_user["firm_id"]
        allowed = {"pending", "prepared", "ca_approved", "filed"}
        if body.status not in allowed:
            return api_response(False, None, f"Invalid status. Allowed: {allowed}")

        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        if body.status in ("ca_approved", "filed") and not body.ca_approved:
            return api_response(False, None,
                "Explicit ca_approved=true required for ca_approved/filed status. CA must confirm.")

        # IT Act §200/§203: only Manager+ can approve/file a TDS return —
        # ca_approved=true alone is a caller-supplied flag, not proof of role.
        if body.status in ("ca_approved", "filed"):
            from core.permissions import can
            role = current_user.get("role", "executive")
            if not can(role, "tds", "approve"):
                return api_response(False, None,
                    "Only Manager or above can approve or file a TDS return.")

        if body.status == "filed" and not (body.prn or "").strip():
            return api_response(False, None,
                "PRN (Provisional Receipt Number) is required to mark a return as filed.")

        if _USE_MOCK:
            current = _MOCK_RETURNS.get(return_id)
            if current is None:
                return api_response(False, None, "Not found")
            current_status = current.get("status")
        else:
            from core.supabase_client import get_supabase
            existing = (
                get_supabase().table("tds_returns").select("status")
                .eq("id", return_id).eq("firm_id", firm_id).limit(1).execute().data
            )
            if not existing:
                return api_response(False, None, "Not found")
            current_status = existing[0].get("status")

        # A return can only be filed once — a repeated/duplicate "mark filed"
        # request (double-click, retry) must not silently overwrite the
        # original PRN/acknowledgement with a second one.
        if body.status == "filed" and current_status == "filed":
            return api_response(False, None, "This return has already been filed.")

        now_iso = datetime.utcnow().isoformat()
        update_payload: dict = {"status": body.status}
        if body.status == "ca_approved":
            update_payload["ca_approved_by"] = current_user.get("id")
            update_payload["ca_approved_at"] = now_iso
        if body.status == "filed":
            update_payload["prn"] = body.prn
            update_payload["ack_number"] = body.ack_number
            update_payload["filed_at"] = body.filing_date or now_iso

        if _USE_MOCK:
            _MOCK_RETURNS[return_id].update(update_payload)
            rec = _MOCK_RETURNS[return_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("tds_returns").update(update_payload).eq("id", return_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else {}

        log_event(firm_id, "tds_return", return_id, "status_change",
                  actor_id=current_user.get("id"), new_data={"status": body.status})
        if body.status == "filed":
            timeline_service.log_timeline_event(
                client_id=rec.get("client_id", ""), firm_id=firm_id,
                financial_year=rec.get("financial_year", ""), category="tds",
                event_type="tds_return_filed",
                title=f"TDS Return {rec.get('return_type', '')} filed for {rec.get('quarter', '')} {rec.get('financial_year', '')}",
                description=f"PRN: {body.prn}" + (f" | Ack: {body.ack_number}" if body.ack_number else ""),
            )
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/certificates")
def list_certificates(
    client_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("tds", "read")),
):
    """List TDS certificates (Form 16/16A) for client. IT Act §203."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [c for c in _MOCK_CERTIFICATES.values() if c["client_id"] == client_id]
            rows = rows[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("tds_certificates").select("*").eq("firm_id", firm_id).eq("client_id", client_id).range(offset, offset + limit - 1).execute().data or []
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/certificates")
def create_certificate(
    body: CreateCertificateRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """
    Generate Form 16/16A DRAFT certificate. IT Act §203.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to TRACES or deductee.
    Draft only — CA must review and sign before issuance.
    """
    try:
        assert_client_access(current_user, body.client_id)
        firm_id = current_user["firm_id"]
        deductee_pan = body.deductee_pan.strip().upper()
        # IT Act §206AA: PAN sentinels ("PANNOTAVBL"/"PANAPPLIED") are valid —
        # same rule domain/tds/tds_computer.py enforces for return computation.
        if not TDSValidator.validate_pan(deductee_pan):
            raise HTTPException(status_code=422,
                                detail=f"Invalid deductee PAN format: '{deductee_pan}'. "
                                       "Expected: AAAAA9999A, or PANNOTAVBL/PANAPPLIED if unavailable.")
        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "deductee_pan": deductee_pan,
            "deductee_name": body.deductee_name,
            "financial_year": body.financial_year,
            "certificate_type": body.certificate_type,
            # tds_certificates has no tds_amount_paise/ca_review_required
            # columns (migration 037) — tds_deducted_paise is the real amount
            # column. status must be one of the real CHECK values ('pending',
            # 'generated', 'issued', 'downloaded') — "pending" is also the
            # column's own DEFAULT and matches "freshly generated, CA review
            # required before issuance" (the frontend badge that already
            # renders regardless of the stored value). section is genuinely
            # missing (migration 232).
            "tds_deducted_paise": body.tds_amount_paise,
            "section": body.section,
            "status": "pending",
            "created_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_CERTIFICATES[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("tds_certificates").insert(record).execute()

        log_event(firm_id, "tds_certificate", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        return api_response(True, record)
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/form26as/upload")
def upload_form26as(
    body: Form26ASUploadRequest,
    current_user: dict = Depends(rbac("tds", "compute")),
):
    """
    Save Form 26AS data and reconcile against tds_deductions. IT Act §203AA.
    Matches by PAN + section + amount.
    """
    try:
        assert_client_access(current_user, body.client_id)
        firm_id = current_user["firm_id"]
        raw = body.raw_data
        # Reconcile 26AS TDS entries against book deductions
        form26as_entries = raw.get("tds_entries", [])  # [{pan, section, amount_paise, deductor_tan}]
        book_deductions = raw.get("book_deductions", [])

        matched = []
        mismatched = []
        missing_in_26as = []

        form26as_keys = {
            (e.get("pan", ""), e.get("section", "")): e for e in form26as_entries
        }

        for book_ded in book_deductions:
            key = (book_ded.get("deductee_pan", ""), book_ded.get("section", ""))
            if key in form26as_keys:
                f26_entry = form26as_keys[key]
                # IT Act §203AA — amounts must match; use integer paise
                book_amt = book_ded.get("amount_paise", 0)
                f26_amt = f26_entry.get("amount_paise", 0)
                if book_amt == f26_amt:
                    matched.append({"key": key, "status": "matched"})
                else:
                    mismatched.append({
                        "key": key, "status": "amount_mismatch",
                        "book_paise": book_amt, "form26as_paise": f26_amt,
                        "diff_paise": abs(book_amt - f26_amt),
                    })
            else:
                missing_in_26as.append({"key": key, "status": "missing_in_26as"})

        reconciliation_result = {
            "matched": matched,
            "mismatched": mismatched,
            "missing_in_26as": missing_in_26as,
            "summary": {
                "total_book": len(book_deductions),
                "matched_count": len(matched),
                "mismatch_count": len(mismatched),
                "missing_count": len(missing_in_26as),
            },
        }

        # form_26as_uploads (migration 052) is file_url/raw_data/
        # reconciliation_result/status/created_by/uploaded_at — record below
        # already matches those real columns exactly, so it's inserted as-is.
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "financial_year": body.financial_year,
            "file_url": body.file_url,
            "raw_data": body.raw_data,
            "reconciliation_result": reconciliation_result,
            "status": "reconciled",
            "created_by": current_user.get("id"),
            "uploaded_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_FORM26AS[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("form_26as_uploads").insert(record).execute()

        log_event(firm_id, "form_26as_upload", record["id"], "create",
                  actor_id=current_user.get("id"))
        return api_response(True, record)
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/form26as/{upload_id}")
def get_form26as(upload_id: str, current_user: dict = Depends(rbac("tds", "read"))):
    """Get Form 26AS reconciliation result."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rec = _MOCK_FORM26AS.get(upload_id)
            if not rec:
                return api_response(False, None, "Not found")
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("form_26as_uploads").select("*").eq("id", upload_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else None
            if not rec:
                return api_response(False, None, "Not found")
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))
