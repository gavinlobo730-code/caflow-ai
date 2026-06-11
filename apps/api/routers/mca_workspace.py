"""
MCA Workspace router — company master, director management, annual and event filings.

Companies Act 2013:
  §92  — MGT-7 annual return
  §137 — AOC-4 financial statements
  §139 — ADT-1 auditor appointment
  §165 — DIR-12 director changes

# CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to MCA21 or any government portal.
"""
from __future__ import annotations

import os
import uuid
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from models.common import api_response
from core.permissions import rbac
from services.audit_service import log_event
from services.timeline_service import timeline_service

router = APIRouter(prefix="/api/mca-workspace", tags=["mca_workspace"])
_logger = logging.getLogger("caflow.mca_workspace")

_USE_MOCK = not os.environ.get("SUPABASE_URL")

# ── Mock stores ───────────────────────────────────────────────────────────────
_MOCK_COMPANIES: dict[str, dict] = {}
_MOCK_DIRECTORS: dict[str, dict] = {}
_MOCK_FILINGS: dict[str, dict] = {}


# ── Request Models ─────────────────────────────────────────────────────────────

class CreateCompanyRequest(BaseModel):
    client_id: str
    cin: str = Field(..., description="Corporate Identification Number")
    company_name: str
    incorporation_date: Optional[str] = None
    registered_address: Optional[str] = None
    authorized_capital_paise: int = Field(default=0, description="Integer paise only")
    paid_up_capital_paise: int = Field(default=0, description="Integer paise only")
    company_type: Optional[str] = None  # PVT, PUB, OPC, LLP


class CreateDirectorRequest(BaseModel):
    client_id: str
    company_id: Optional[str] = None
    din: str = Field(..., description="8-digit Director Identification Number")
    name: str
    designation: str
    date_of_appointment: str = Field(..., description="YYYY-MM-DD")
    pan: Optional[str] = None
    email: Optional[str] = None
    kyc_status: str = Field(default="pending", description="active, pending, expired")


class UpdateDirectorRequest(BaseModel):
    kyc_status: Optional[str] = None
    date_of_cessation: Optional[str] = None
    designation: Optional[str] = None


class CreateFilingRequest(BaseModel):
    client_id: str
    company_id: Optional[str] = None
    form_type: str = Field(..., description="AOC-4, MGT-7, ADT-1, DIR-12, INC-22, SH-7, CHG-1, CHG-4")
    financial_year: Optional[str] = None  # e.g. 2025-26
    period: Optional[str] = None
    due_date: Optional[str] = None
    description: Optional[str] = None


class UpdateFilingStatusRequest(BaseModel):
    status: str
    ca_approved: bool = False
    srn: Optional[str] = None
    filing_date: Optional[str] = None
    acknowledgement_url: Optional[str] = None


# Annual filing forms
_ANNUAL_FORMS = {"AOC-4", "MGT-7", "ADT-1"}
# Event filing forms
_EVENT_FORMS = {"DIR-12", "INC-22", "SH-7", "CHG-1", "CHG-4"}


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/companies")
def list_companies(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("mca", "read")),
):
    """List MCA companies for a client."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [c for c in _MOCK_COMPANIES.values() if c["client_id"] == client_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("mca_companies").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/companies")
def create_company(
    body: CreateCompanyRequest,
    current_user: dict = Depends(rbac("mca", "write")),
):
    """Create or register company master record."""
    try:
        firm_id = current_user["firm_id"]
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "cin": body.cin,
            "company_name": body.company_name,
            "incorporation_date": body.incorporation_date,
            "registered_address": body.registered_address,
            "authorized_capital_paise": body.authorized_capital_paise,
            "paid_up_capital_paise": body.paid_up_capital_paise,
            "company_type": body.company_type,
            "created_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_COMPANIES[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("mca_companies").insert(record).execute()

        log_event(firm_id, "mca_company", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        return api_response(True, record)
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/companies/{company_id}")
def get_company(company_id: str, current_user: dict = Depends(rbac("mca", "read"))):
    """Get company with its directors."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            company = _MOCK_COMPANIES.get(company_id)
            if not company:
                return api_response(False, None, "Company not found")
            directors = [d for d in _MOCK_DIRECTORS.values()
                         if d.get("company_id") == company_id]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            rows = sb.table("mca_companies").select("*").eq("id", company_id).eq("firm_id", firm_id).execute().data
            if not rows:
                return api_response(False, None, "Company not found")
            company = rows[0]
            directors = sb.table("mca_directors").select("*").eq("company_id", company_id).eq("firm_id", firm_id).execute().data or []

        return api_response(True, {**company, "directors": directors})
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/directors")
def list_directors(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("mca", "read")),
):
    """List directors/DINs for a client."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [d for d in _MOCK_DIRECTORS.values() if d["client_id"] == client_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("mca_directors").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/directors")
def create_director(
    body: CreateDirectorRequest,
    current_user: dict = Depends(rbac("mca", "write")),
):
    """Add director with DIN. Companies Act 2013 §165."""
    try:
        firm_id = current_user["firm_id"]
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "company_id": body.company_id,
            "din": body.din,
            "name": body.name,
            "designation": body.designation,
            "date_of_appointment": body.date_of_appointment,
            "pan": body.pan,
            "email": body.email,
            "kyc_status": body.kyc_status,
            "date_of_cessation": None,
            "created_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_DIRECTORS[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("mca_directors").insert(record).execute()

        log_event(firm_id, "mca_director", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        return api_response(True, record)
    except Exception as e:
        return api_response(False, None, str(e))


@router.patch("/directors/{director_id}")
def update_director(
    director_id: str,
    body: UpdateDirectorRequest,
    current_user: dict = Depends(rbac("mca", "write")),
):
    """Update director KYC status or cessation date."""
    try:
        firm_id = current_user["firm_id"]
        updates = {k: v for k, v in body.model_dump().items() if v is not None}
        if not updates:
            return api_response(False, None, "No update fields provided")

        if _USE_MOCK:
            if director_id not in _MOCK_DIRECTORS:
                return api_response(False, None, "Director not found")
            _MOCK_DIRECTORS[director_id].update(updates)
            rec = _MOCK_DIRECTORS[director_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("mca_directors").update(updates).eq("id", director_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else {}

        log_event(firm_id, "mca_director", director_id, "update",
                  actor_id=current_user.get("id"), new_data=updates)
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/filings")
def list_filings(
    client_id: str = Query(...),
    company_id: Optional[str] = Query(None),
    form_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("mca", "read")),
):
    """List MCA filings. Filter by company, form type, or status."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [f for f in _MOCK_FILINGS.values() if f["client_id"] == client_id]
            if company_id:
                rows = [f for f in rows if f.get("company_id") == company_id]
            if form_type:
                rows = [f for f in rows if f.get("form_type") == form_type]
            if status:
                rows = [f for f in rows if f.get("status") == status]
            rows = rows[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            sb = get_supabase()
            q = sb.table("mca_filings").select("*").eq("firm_id", firm_id).eq("client_id", client_id)
            if company_id:
                q = q.eq("company_id", company_id)
            if form_type:
                q = q.eq("form_type", form_type)
            if status:
                q = q.eq("status", status)
            rows = q.range(offset, offset + limit - 1).execute().data or []

        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))


@router.post("/filings")
def create_filing(
    body: CreateFilingRequest,
    current_user: dict = Depends(rbac("mca", "write")),
):
    """
    Create an MCA filing record.
    Annual: AOC-4 (§137), MGT-7 (§92), ADT-1 (§139).
    Event: DIR-12 (§165), INC-22, SH-7, CHG-1, CHG-4.
    """
    try:
        firm_id = current_user["firm_id"]
        valid_forms = _ANNUAL_FORMS | _EVENT_FORMS
        if body.form_type not in valid_forms:
            return api_response(False, None, f"Invalid form_type. Must be one of: {sorted(valid_forms)}")

        category = "annual" if body.form_type in _ANNUAL_FORMS else "event"

        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "company_id": body.company_id,
            "form_type": body.form_type,
            "category": category,
            "financial_year": body.financial_year,
            "period": body.period,
            "due_date": body.due_date,
            "description": body.description,
            "status": "not_started",
            "srn": None,
            "filing_date": None,
            "acknowledgement_url": None,
            "created_at": datetime.utcnow().isoformat(),
        }

        if _USE_MOCK:
            _MOCK_FILINGS[record["id"]] = record
        else:
            from core.supabase_client import get_supabase
            get_supabase().table("mca_filings").insert(record).execute()

        log_event(firm_id, "mca_filing", record["id"], "create",
                  actor_id=current_user.get("id"), new_data=record)
        return api_response(True, record)
    except Exception as e:
        return api_response(False, None, str(e))


@router.patch("/filings/{filing_id}/status")
def update_filing_status(
    filing_id: str,
    body: UpdateFilingStatusRequest,
    current_user: dict = Depends(rbac("mca", "write")),
):
    """
    Update MCA filing status: not_started → in_progress → filed.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to MCA21.
    """
    try:
        firm_id = current_user["firm_id"]
        allowed = {"not_started", "in_progress", "filed", "overdue"}
        if body.status not in allowed:
            return api_response(False, None, f"Invalid status. Allowed: {allowed}")

        # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        if body.status == "filed" and not body.ca_approved:
            return api_response(False, None,
                "Explicit ca_approved=true required for filed status. CA must confirm.")

        # # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
        # Companies Act §92/137/139: Only Manager+ can mark filing as filed
        if body.status == "filed":
            from core.permissions import can
            role = current_user.get("role", "executive")
            if not can(role, "mca", "approve"):
                raise HTTPException(status_code=403, detail="Only Manager or above can mark filings as filed")

        updates: dict = {"status": body.status}
        if body.srn:
            updates["srn"] = body.srn
        if body.filing_date:
            updates["filing_date"] = body.filing_date
        if body.acknowledgement_url:
            updates["acknowledgement_url"] = body.acknowledgement_url

        if _USE_MOCK:
            if filing_id not in _MOCK_FILINGS:
                return api_response(False, None, "Filing not found")
            _MOCK_FILINGS[filing_id].update(updates)
            rec = _MOCK_FILINGS[filing_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("mca_filings").update(updates).eq("id", filing_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else {}

        log_event(firm_id, "mca_filing", filing_id, "status_change",
                  actor_id=current_user.get("id"), new_data=updates)
        if body.status == "filed":
            timeline_service.log_timeline_event(
                client_id=rec.get("client_id", ""), firm_id=firm_id,
                financial_year=rec.get("financial_year", ""), category="mca",
                event_type="mca_filing_done",
                title=f"MCA {rec.get('form_type', '')} filed — SRN: {body.srn or 'N/A'}",
            )
        return api_response(True, rec)
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/filings/{filing_id}")
def get_filing(filing_id: str, current_user: dict = Depends(rbac("mca", "read"))):
    """Get MCA filing details."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rec = _MOCK_FILINGS.get(filing_id)
            if not rec:
                return api_response(False, None, "Filing not found")
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("mca_filings").select("*").eq("id", filing_id).eq("firm_id", firm_id).execute().data
            rec = rows[0] if rows else None
            if not rec:
                return api_response(False, None, "Filing not found")
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, str(e))


@router.get("/filing-history")
def filing_history(
    client_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("mca", "read")),
):
    """List filed MCA records with SRN and acknowledgement."""
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [f for f in _MOCK_FILINGS.values()
                    if f["client_id"] == client_id and f.get("status") == "filed"]
            rows = rows[offset:offset + limit]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("mca_filings").select("*").eq("firm_id", firm_id).eq("client_id", client_id).eq("status", "filed").range(offset, offset + limit - 1).execute().data or []
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, str(e))
