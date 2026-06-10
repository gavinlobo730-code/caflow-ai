"""
GST Workspace router — filing dashboard, return management, GSTR-2B reconciliation.

CGST Act §37 (GSTR-1 outward supplies), §39 (GSTR-3B monthly return), §44 (GSTR-9 annual).
All monetary amounts in integer paise — never float.

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to GSTN or any government portal.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import date, datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from models.common import api_response
from core.permissions import rbac
from services.audit_service import log_event
from services.timeline_service import timeline_service
from services.period_validation_service import period_validation_service

router = APIRouter(prefix="/api/gst-workspace", tags=["gst_workspace"])
_logger = logging.getLogger("caflow.gst_workspace")

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# ── Mock stores ───────────────────────────────────────────────────────────────
_MOCK_GSTR1: dict[str, dict] = {}
_MOCK_GSTR3B: dict[str, dict] = {}
_MOCK_GSTR2B: dict[str, dict] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _gstr1_due_date(period: str) -> str:
    """CGST Act §37 — GSTR-1 due 11th of month following the return period."""
    mm = int(period[:2])
    yyyy = int(period[2:])
    next_month = mm % 12 + 1
    next_year = yyyy + (1 if mm == 12 else 0)
    return f"{next_year}-{next_month:02d}-11"


def _gstr3b_due_date(period: str) -> str:
    """CGST Act §39 — GSTR-3B due 20th of month following the return period."""
    mm = int(period[:2])
    yyyy = int(period[2:])
    next_month = mm % 12 + 1
    next_year = yyyy + (1 if mm == 12 else 0)
    return f"{next_year}-{next_month:02d}-20"


# ── Request Models ─────────────────────────────────────────────────────────────

class SaveGSTR1Request(BaseModel):
    client_id: str
    period: str = Field(..., description="MMYYYY e.g. 042025")
    gstin: str
    payload_json: dict = Field(default_factory=dict)
    summary_json: dict = Field(default_factory=dict)
    total_taxable_paise: int = Field(default=0, description="Integer paise only")
    total_igst_paise: int = Field(default=0)
    total_cgst_paise: int = Field(default=0)
    total_sgst_paise: int = Field(default=0)
    total_cess_paise: int = Field(default=0)


class SaveGSTR3BRequest(BaseModel):
    client_id: str
    period: str = Field(..., description="MMYYYY e.g. 042025")
    gstin: str
    payload_json: dict = Field(default_factory=dict)
    summary_json: dict = Field(default_factory=dict)
    tax_liability_paise: int = Field(default=0)
    itc_claimed_paise: int = Field(default=0)
    net_tax_paise: int = Field(default=0)


class UpdateStatusRequest(BaseModel):
    status: str
    ca_approved: bool = False


class GSTR2BUploadRequest(BaseModel):
    client_id: str
    period: str
    file_url: Optional[str] = None
    raw_data: dict = Field(default_factory=dict, description="GSTR-2B JSON from portal")


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/")
def gst_dashboard(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """GST filing dashboard with upcoming due dates."""
    try:
        firm_id = current_user["firm_id"]
        today = date.today()
        current_period = f"{today.month:02d}{today.year}"

        if _USE_MOCK:
            gstr1_list = [r for r in _MOCK_GSTR1.values() if r["client_id"] == client_id]
            gstr3b_list = [r for r in _MOCK_GSTR3B.values() if r["client_id"] == client_id]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            gstr1_list = sb.table("gstr1_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
            gstr3b_list = sb.table("gstr3b_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []

        return api_response(True, {
            "gstr1_returns": gstr1_list,
            "gstr3b_returns": gstr3b_list,
            "upcoming_due_dates": {
                "gstr1": _gstr1_due_date(current_period),
                "gstr3b": _gstr3b_due_date(current_period),
                "current_period": current_period,
            },
        })
    except Exception as e:
        _logger.exception("gst_dashboard error")
        return api_response(False, None, str(e))


@router.get("/returns")
def list_returns(
    client_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """List all GST returns (GSTR-1 + GSTR-3B) for a client."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            g1 = [r for r in _MOCK_GSTR1.values() if r["client_id"] == client_id]
            g3b = [r for r in _MOCK_GSTR3B.values() if r["client_id"] == client_id]
            g1 = g1[offset:offset + limit]
            g3b = g3b[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            g1 = sb.table("gstr1_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).range(offset, offset + limit - 1).execute().data or []
            g3b = sb.table("gstr3b_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).range(offset, offset + limit - 1).execute().data or []

        return api_response(True, {"gstr1": g1, "gstr3b": g3b})
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/gstr1")
def save_gstr1(
    body: SaveGSTR1Request,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Save GSTR-1 return as draft. CGST Act §37."""
    try:
        firm_id = current_user["firm_id"]
        # Validate period date
        period_date = f"{body.period[2:]}-{body.period[:2]}-01"
        period_validation_service.validate_posting_date(firm_id, period_date)

        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "period": body.period,
            "gstin": body.gstin,
            "payload_json": body.payload_json,
            "summary_json": body.summary_json,
            "total_taxable_paise": body.total_taxable_paise,
            "total_igst_paise": body.total_igst_paise,
            "total_cgst_paise": body.total_cgst_paise,
            "total_sgst_paise": body.total_sgst_paise,
            "total_cess_paise": body.total_cess_paise,
            "status": "draft",
            "created_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_GSTR1[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("gstr1_returns").insert(record).execute()

        log_event(firm_id, "gstr1_return", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        timeline_service.log_timeline_event(
            client_id=body.client_id, firm_id=firm_id,
            financial_year="", category="gst", event_type="gstr1_draft_saved",
            title=f"GSTR-1 draft saved for {body.period}",
        )
        return api_response(True, record)
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/gstr1/{return_id}")
def get_gstr1(return_id: str, current_user: dict = Depends(rbac("gst", "read"))):
    """Get GSTR-1 return by ID."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rec = _MOCK_GSTR1.get(return_id)
            if not rec:
                return api_response(False, None, "Not found")
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("gstr1_returns").select("*").eq("id", return_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else None
            if not rec:
                return api_response(False, None, "Not found")

        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))


@router.patch("/gstr1/{return_id}/status")
def update_gstr1_status(
    return_id: str,
    body: UpdateStatusRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """
    Update GSTR-1 status: draft → validated → ca_approved.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to GSTN.
    """
    try:
        firm_id = current_user["firm_id"]
        allowed = {"draft", "validated", "ca_approved", "submitted"}
        if body.status not in allowed:
            return api_response(False, None, f"Invalid status. Allowed: {allowed}")

        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        if body.status in ("ca_approved", "submitted") and not body.ca_approved:
            return api_response(False, None,
                "Explicit ca_approved=true required for ca_approved/submitted status. CA must confirm.")

        if _USE_MOCK:
            if return_id not in _MOCK_GSTR1:
                return api_response(False, None, "Not found")
            _MOCK_GSTR1[return_id]["status"] = body.status
            rec = _MOCK_GSTR1[return_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("gstr1_returns").update({"status": body.status}).eq("id", return_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else {}

        log_event(firm_id, "gstr1_return", return_id, "status_change",
                  actor_id=current_user.get("id"), new_data={"status": body.status})
        if body.status == "submitted":
            timeline_service.log_timeline_event(
                client_id=rec.get("client_id", ""), firm_id=firm_id,
                financial_year="", category="gst", event_type="gstr1_filed",
                title=f"GSTR-1 filed for {rec.get('period', '')}",
            )
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/gstr3b")
def save_gstr3b(
    body: SaveGSTR3BRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """Save GSTR-3B return as draft. CGST Act §39."""
    try:
        firm_id = current_user["firm_id"]
        period_date = f"{body.period[2:]}-{body.period[:2]}-01"
        period_validation_service.validate_posting_date(firm_id, period_date)

        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "period": body.period,
            "gstin": body.gstin,
            "payload_json": body.payload_json,
            "summary_json": body.summary_json,
            "tax_liability_paise": body.tax_liability_paise,
            "itc_claimed_paise": body.itc_claimed_paise,
            "net_tax_paise": body.net_tax_paise,
            "status": "draft",
            "created_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_GSTR3B[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("gstr3b_returns").insert(record).execute()

        log_event(firm_id, "gstr3b_return", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        return api_response(True, record)
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/gstr3b/{return_id}")
def get_gstr3b(return_id: str, current_user: dict = Depends(rbac("gst", "read"))):
    """Get GSTR-3B return by ID."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rec = _MOCK_GSTR3B.get(return_id)
            if not rec:
                return api_response(False, None, "Not found")
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("gstr3b_returns").select("*").eq("id", return_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else None
            if not rec:
                return api_response(False, None, "Not found")

        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))


@router.patch("/gstr3b/{return_id}/status")
def update_gstr3b_status(
    return_id: str,
    body: UpdateStatusRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """
    Update GSTR-3B status: draft → validated → ca_approved.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to GSTN.
    """
    try:
        firm_id = current_user["firm_id"]
        allowed = {"draft", "validated", "ca_approved", "submitted"}
        if body.status not in allowed:
            return api_response(False, None, f"Invalid status. Allowed: {allowed}")

        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        if body.status in ("ca_approved", "submitted") and not body.ca_approved:
            return api_response(False, None,
                "Explicit ca_approved=true required for ca_approved/submitted status. CA must confirm.")

        if _USE_MOCK:
            if return_id not in _MOCK_GSTR3B:
                return api_response(False, None, "Not found")
            _MOCK_GSTR3B[return_id]["status"] = body.status
            rec = _MOCK_GSTR3B[return_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("gstr3b_returns").update({"status": body.status}).eq("id", return_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else {}

        log_event(firm_id, "gstr3b_return", return_id, "status_change",
                  actor_id=current_user.get("id"), new_data={"status": body.status})
        if body.status == "submitted":
            timeline_service.log_timeline_event(
                client_id=rec.get("client_id", ""), firm_id=firm_id,
                financial_year="", category="gst", event_type="gstr3b_filed",
                title=f"GSTR-3B filed for {rec.get('period', '')}",
            )
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/filing-history")
def filing_history(
    client_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("gst", "read")),
):
    """List filed returns (status=submitted) with ARN and filing date."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            g1 = [r for r in _MOCK_GSTR1.values()
                  if r["client_id"] == client_id and r.get("status") == "submitted"]
            g3b = [r for r in _MOCK_GSTR3B.values()
                   if r["client_id"] == client_id and r.get("status") == "submitted"]
            g1 = g1[offset:offset + limit]
            g3b = g3b[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            g1 = sb.table("gstr1_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "submitted").range(offset, offset + limit - 1).execute().data or []
            g3b = sb.table("gstr3b_returns").select("*").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "submitted").range(offset, offset + limit - 1).execute().data or []

        return api_response(True, {"gstr1_filed": g1, "gstr3b_filed": g3b})
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/gstr2b/upload")
def upload_gstr2b(
    body: GSTR2BUploadRequest,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """
    Save GSTR-2B JSON and reconcile against books.
    Matches invoices by invoice_no + GSTIN. CGST Act §38.
    """
    try:
        firm_id = current_user["firm_id"]
        raw = body.raw_data
        # Reconcile: extract invoices from GSTR-2B and match against books
        b2b_invoices = raw.get("data", {}).get("docDetails", []) or raw.get("invoices", [])
        matched = []
        mismatched = []
        missing_in_2b = []

        book_invoices = raw.get("book_invoices", [])  # caller provides book invoices for matching
        b2b_keys = {(inv.get("inum", ""), inv.get("sgstin", "")): inv for inv in b2b_invoices}

        for book_inv in book_invoices:
            key = (book_inv.get("invoice_no", ""), book_inv.get("gstin", ""))
            if key in b2b_keys:
                b2b_inv = b2b_keys[key]
                # Compare amounts in integer paise
                book_taxable = book_inv.get("taxable_paise", 0)
                b2b_taxable = int(round(b2b_inv.get("txval", 0) * 100))
                if book_taxable == b2b_taxable:
                    matched.append({"key": key, "status": "matched"})
                else:
                    mismatched.append({
                        "key": key, "status": "amount_mismatch",
                        "book_paise": book_taxable, "gstr2b_paise": b2b_taxable,
                    })
            else:
                missing_in_2b.append({"key": key, "status": "missing_in_2b"})

        reconciliation_result = {
            "matched": matched,
            "mismatched": mismatched,
            "missing_in_2b": missing_in_2b,
            "summary": {
                "total_book": len(book_invoices),
                "matched_count": len(matched),
                "mismatch_count": len(mismatched),
                "missing_count": len(missing_in_2b),
            },
        }

        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "period": body.period,
            "file_url": body.file_url,
            "raw_data": body.raw_data,
            "reconciliation_result": reconciliation_result,
            "status": "reconciled",
            "created_by": current_user.get("id"),
            "uploaded_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_GSTR2B[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("gstr2b_uploads").insert(record).execute()

        if mismatched or missing_in_2b:
            timeline_service.log_timeline_event(
                client_id=body.client_id, firm_id=firm_id,
                financial_year="", category="gst", event_type="gst_mismatch_detected",
                title=f"GSTR-2B mismatch for {body.period}: {len(mismatched)} mismatches, {len(missing_in_2b)} missing",
                severity="warning",
            )
        return api_response(True, record)
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/gstr9")
def save_gstr9(
    data: dict,
    current_user: dict = Depends(rbac("gst", "compute")),
):
    """
    Save GSTR-9 annual return draft.
    CGST Act §44: Annual return to be filed by 31st December following FY end.
    All amounts in integer paise.
    """
    try:
        required = ["client_id", "financial_year"]
        for field in required:
            if not data.get(field):
                raise HTTPException(status_code=422, detail=f"{field} is required")

        firm_id   = current_user.get("firm_id")
        client_id = data["client_id"]
        fy        = data["financial_year"]  # e.g. "2025-26"

        # CGST Act §44 — GSTR-9 is annual; use April 1 of the FY for period validation
        fy_start_year = int(fy.split("-")[0]) if fy else datetime.now(timezone.utc).year
        period_validation_service.validate_posting_date(firm_id or "", f"{fy_start_year}-04-01")

        payload = {
            "firm_id":              firm_id,
            "client_id":            client_id,
            "financial_year":       fy,
            "period":               f"FY{fy}",
            "return_type":          "gstr9",
            "status":               "draft",
            "payload_json":         data.get("payload_json", {}),
            "summary_json":         data.get("summary_json", {}),
            "total_taxable_paise":  int(data.get("total_taxable_paise", 0)),
            "total_igst_paise":     int(data.get("total_igst_paise", 0)),
            "total_cgst_paise":     int(data.get("total_cgst_paise", 0)),
            "total_sgst_paise":     int(data.get("total_sgst_paise", 0)),
            "total_tax_paise":      int(data.get("total_tax_paise", 0)),
            "created_at":           datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            rec = {**payload, "id": str(uuid.uuid4())}
            _MOCK_GSTR1[rec["id"]] = rec  # reuse same mock store
            return api_response(True, rec)

        from core.supabase_client import get_supabase
        db = get_supabase()
        # CGST Act §44: GSTR-9 unique per client per FY
        existing = db.table("gstr1_returns").select("id").eq("client_id", client_id).eq("financial_year", fy).eq("return_type", "gstr9").limit(1).execute()
        if existing.data:
            # Update existing draft
            upd = db.table("gstr1_returns").update(payload).eq("id", existing.data[0]["id"]).execute()
            rec = upd.data[0] if upd.data else {**payload, "id": existing.data[0]["id"]}
        else:
            ins = db.table("gstr1_returns").insert(payload).execute()
            rec = ins.data[0] if ins.data else payload

        log_event(
            firm_id or "", "gstr9_return", rec.get("id", ""),
            "create", actor_id=current_user.get("auth_user_id"),
            actor_email=current_user.get("email"), new_data=rec,
        )
        return api_response(True, rec)
    except HTTPException:
        raise
    except Exception as e:
        _logger.error("save_gstr9: %s", e)
        return api_response(False, None, str(e))


@router.get("/gstr2b/{upload_id}")
def get_gstr2b(upload_id: str, current_user: dict = Depends(rbac("gst", "read"))):
    """Get GSTR-2B reconciliation result."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rec = _MOCK_GSTR2B.get(upload_id)
            if not rec:
                return api_response(False, None, "Not found")
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("gstr2b_uploads").select("*").eq("id", upload_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else None
            if not rec:
                return api_response(False, None, "Not found")

        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))
