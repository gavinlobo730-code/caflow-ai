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
from datetime import datetime, date
from core.ist_clock import ist_today
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client
from core.validators import validate_cin, validate_din, validate_pan
from services.audit_service import log_event
from services.timeline_service import timeline_service
from services.compliance_engine import mca_due_date

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

# CompaniesTab's <select> sends the short form (frontend); mca_companies.company_category's
# CHECK constraint (migration 038) requires the full Companies Act 2013 term. Anything not
# in this map (e.g. "Section 8", "Nidhi" sent directly) passes through unchanged.
_COMPANY_TYPE_MAP = {"PVT": "Private Limited", "PUB": "Public Limited"}


# ── Client-assignment scope (M2) ──────────────────────────────────────────────
# The third router in a row with this shape: assert_client_access on the POST
# bodies (create_company / create_director / create_filing) and nothing on the
# endpoints that take their client from a QUERY PARAMETER or address a row by
# id. Any member of the firm could read any client's company master, its
# directors and DINs, and every MCA filing with its SRN.
#
# Same two answers as tds_workspace and gst_workspace:
#   * NAMED client  → assert_client_access (404), placed BEFORE the `try`, since
#     every handler ends in a bare `except Exception: return api_response(False,
#     ...)` that would otherwise swallow the refusal into a 200.
#   * ROW id → `_load_or_none`, because a missing row here is a 200 carrying
#     {"success": false, "error": "... not found"}; a 404 refusal would make the
#     status code an oracle for which ids are real.

def _visible_or_none(current_user: dict, rec: Optional[dict]) -> Optional[dict]:
    """`rec` if the caller may see its client, otherwise None."""
    if rec is None:
        return None
    if not can_access_client(current_user, rec.get("client_id")):
        return None
    return rec


def _load_or_none(current_user: dict, table: str, mock_store: dict,
                  row_id: str) -> Optional[dict]:
    """Read a row the caller may see, or None.

    Both PATCH endpoints had NO read at all — they fired the UPDATE and used
    whatever came back, which cannot check a client: by then the director's KYC
    status or the filing's SRN has already been written. The read is added so
    the refusal happens first.
    """
    if _USE_MOCK:
        rec = mock_store.get(row_id)
    else:
        from core.supabase_client import get_supabase
        rows = (get_supabase().table(table).select("*")
                .eq("id", row_id).eq("firm_id", current_user.get("firm_id"))
                .execute().data)
        rec = rows[0] if rows else None
    return _visible_or_none(current_user, rec)


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.get("/companies")
def list_companies(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("mca", "read")),
):
    """List MCA companies for a client."""
    assert_client_access(current_user, client_id)
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [c for c in _MOCK_COMPANIES.values() if c["client_id"] == client_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("mca_companies").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, "Unable to complete MCA operation. Please try again.")


@router.post("/companies")
def create_company(
    body: CreateCompanyRequest,
    current_user: dict = Depends(rbac("mca", "write")),
):
    """Create or register company master record."""
    try:
        assert_client_access(current_user, body.client_id)
        firm_id = current_user["firm_id"]
        cin = body.cin.strip().upper()
        err = validate_cin(cin)
        if err:
            raise HTTPException(status_code=422, detail=err)
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "cin": cin,
            "company_name": body.company_name,
            # Real columns are incorp_date/registered_office/company_category
            # (migration 038) — the request model keeps the frontend's field
            # names, mapped here (task #219 schema-drift fix).
            "incorp_date": body.incorporation_date,
            "registered_office": body.registered_address,
            "authorized_capital_paise": body.authorized_capital_paise,
            "paid_up_capital_paise": body.paid_up_capital_paise,
            "company_category": (_COMPANY_TYPE_MAP.get(body.company_type, body.company_type)
                                  if body.company_type else "Private Limited"),
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
    except HTTPException:
        # A CIN-format rejection carries a real, actionable message — collapsing
        # it into "Please try again" would hide exactly what needs to change.
        raise
    except Exception as e:
        return api_response(False, None, "Unable to complete MCA operation. Please try again.")


@router.get("/companies/{company_id}")
def get_company(company_id: str, current_user: dict = Depends(rbac("mca", "read"))):
    """Get company with its directors."""
    try:
        firm_id = current_user["firm_id"]
        company = _load_or_none(current_user, "mca_companies", _MOCK_COMPANIES,
                                company_id)
        if not company:
            return api_response(False, None, "Company not found")
        # The directors ride along on the company's own check — same client by
        # construction, and the query is scoped to this company and this firm.
        if _USE_MOCK:
            directors = [d for d in _MOCK_DIRECTORS.values()
                         if d.get("company_id") == company_id]
        else:
            from core.supabase_client import get_supabase
            directors = get_supabase().table("mca_directors").select("*").eq("company_id", company_id).eq("firm_id", firm_id).execute().data or []

        return api_response(True, {**company, "directors": directors})
    except Exception as e:
        return api_response(False, None, "Unable to complete MCA operation. Please try again.")


@router.get("/directors")
def list_directors(
    client_id: str = Query(...),
    current_user: dict = Depends(rbac("mca", "read")),
):
    """List directors/DINs for a client."""
    assert_client_access(current_user, client_id)
    try:
        firm_id = current_user["firm_id"]
        if _USE_MOCK:
            rows = [d for d in _MOCK_DIRECTORS.values() if d["client_id"] == client_id]
        else:
            from core.supabase_client import get_supabase
            rows = get_supabase().table("mca_directors").select("*").eq("firm_id", firm_id).eq("client_id", client_id).execute().data or []
        return api_response(True, rows)
    except Exception as e:
        return api_response(False, None, "Unable to complete MCA operation. Please try again.")


@router.post("/directors")
def create_director(
    body: CreateDirectorRequest,
    current_user: dict = Depends(rbac("mca", "write")),
):
    """Add director with DIN. Companies Act 2013 §165."""
    try:
        assert_client_access(current_user, body.client_id)
        firm_id = current_user["firm_id"]
        din = body.din.strip()
        err = validate_din(din)
        if err:
            raise HTTPException(status_code=422, detail=err)
        pan = body.pan.strip().upper() if body.pan else body.pan
        if pan:
            err = validate_pan(pan)
            if err:
                raise HTTPException(status_code=422, detail=err)
        record = {
            "id": str(uuid.uuid4()),
            "firm_id": firm_id,
            "client_id": body.client_id,
            "company_id": body.company_id,
            "din": din,
            # Real column is director_name (migration 038); request model
            # keeps the frontend's "name" field (task #219 schema-drift fix).
            "director_name": body.name,
            "designation": body.designation,
            "date_of_appointment": body.date_of_appointment,
            "pan": pan,
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
    except HTTPException:
        # A DIN/PAN-format rejection carries a real, actionable message —
        # collapsing it into "Please try again" would hide exactly what needs
        # to change.
        raise
    except Exception as e:
        return api_response(False, None, "Unable to complete MCA operation. Please try again.")


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

        # Read first: this writes KYC status and cessation dates onto a named
        # director (Companies Act §164/§167). A check after the write is none.
        if _load_or_none(current_user, "mca_directors", _MOCK_DIRECTORS,
                         director_id) is None:
            return api_response(False, None, "Director not found")

        if _USE_MOCK:
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
        return api_response(False, None, "Unable to complete MCA operation. Please try again.")


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
    assert_client_access(current_user, client_id)
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
        return api_response(False, None, "Unable to complete MCA operation. Please try again.")


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
        assert_client_access(current_user, body.client_id)
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
            # mca_filings has no "description" column; reuses the existing
            # free-text "notes" column instead of adding a duplicate one
            # (task #219 schema-drift fix).
            "notes": body.description,
            "status": "not_started",
            "srn": None,
            # Real column is filed_date (migration 012); request/response
            # keep "filing_date" as the API field name, mapped below.
            "filed_date": None,
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
    except HTTPException:
        raise
    except Exception as e:
        return api_response(False, None, "Unable to complete MCA operation. Please try again.")


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
            # Real column is filed_date (migration 012); request field keeps
            # the frontend's "filing_date" name, mapped here.
            updates["filed_date"] = body.filing_date
        if body.acknowledgement_url:
            updates["acknowledgement_url"] = body.acknowledgement_url

        # Read first: marking a filing "filed" writes the MCA21 SRN and
        # acknowledgement onto it (Companies Act §92/§137/§139).
        if _load_or_none(current_user, "mca_filings", _MOCK_FILINGS,
                         filing_id) is None:
            return api_response(False, None, "Filing not found")

        if _USE_MOCK:
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
        return api_response(False, None, "Unable to complete MCA operation. Please try again.")


@router.get("/filings/{filing_id}")
def get_filing(filing_id: str, current_user: dict = Depends(rbac("mca", "read"))):
    """Get MCA filing details."""
    try:
        firm_id = current_user["firm_id"]
        rec = _load_or_none(current_user, "mca_filings", _MOCK_FILINGS, filing_id)
        if not rec:
            return api_response(False, None, "Filing not found")
        return api_response(True, rec)
    except Exception as e:
        return api_response(False, None, "Unable to complete MCA operation. Please try again.")


@router.put("/filings/{filing_id}/complete")
def complete_filing(
    filing_id: str,
    body: UpdateFilingStatusRequest,
    current_user: dict = Depends(rbac("mca", "write")),
):
    """
    Mark a filing as complete with SRN and acknowledgement.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to MCA21 or any government portal.
    Companies Act §92/137/139/165: CA must explicitly confirm before marking filed.
    """
    # # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT
    body_with_filed = UpdateFilingStatusRequest(
        status="filed",
        ca_approved=body.ca_approved,
        srn=body.srn,
        filing_date=body.filing_date or ist_today().isoformat(),
        acknowledgement_url=body.acknowledgement_url,
    )
    return update_filing_status(filing_id, body_with_filed, current_user)


@router.get("/calendar")
def mca_calendar(
    client_id: str = Query(...),
    agm_date: str = Query(..., description="AGM date in YYYY-MM-DD format"),
    current_user: dict = Depends(rbac("mca", "read")),
):
    """
    Generate upcoming MCA deadlines based on AGM date.
    Companies Act 2013:
      §92  — MGT-7: AGM + 60 days
      §137 — AOC-4: AGM + 30 days
      §139 — ADT-1: AGM + 15 days

    Returns filing calendar with form, due date, days remaining, and status.
    # CA REVIEW REQUIRED — DO NOT AUTO-SUBMIT to MCA21.
    """
    # The arithmetic here needs no database — but the caller is asking for a
    # named client's statutory calendar, and the id is echoed through the
    # response. Guarded on the same reasoning as the TDS /compute pair: the
    # field is required by the signature, so an exemption would be true today
    # and silently false the first time somebody reads stored data here.
    assert_client_access(current_user, client_id)
    try:
        try:
            agm_dt = date.fromisoformat(agm_date)
        except ValueError:
            return api_response(False, None, "Invalid agm_date format. Use YYYY-MM-DD.")

        today = ist_today()

        # Companies Act §92/137/139 — deadline computation from AGM date.
        # R3.1: offsets sourced from compliance_engine.MCA_AGM_OFFSET_DAYS,
        # the same constants services/compliance_obligation_service.py's
        # _roc_obligations uses — previously hardcoded independently here.
        annual_forms = [
            {
                "form_type": "ADT-1",
                "description": "Auditor Appointment — Companies Act 2013 §139",
                "due_date": mca_due_date(agm_dt, "ADT-1").isoformat(),
                "days_from_agm": 15,
            },
            {
                "form_type": "AOC-4",
                "description": "Financial Statements — Companies Act 2013 §137",
                "due_date": mca_due_date(agm_dt, "AOC-4").isoformat(),
                "days_from_agm": 30,
            },
            {
                "form_type": "MGT-7",
                "description": "Annual Return — Companies Act 2013 §92",
                "due_date": mca_due_date(agm_dt, "MGT-7").isoformat(),
                "days_from_agm": 60,
            },
        ]

        # Enrich with days_remaining and status
        calendar = []
        for entry in annual_forms:
            due_dt = date.fromisoformat(entry["due_date"])
            days_remaining = (due_dt - today).days
            status = "overdue" if days_remaining < 0 else ("due_soon" if days_remaining <= 30 else "upcoming")
            calendar.append({
                **entry,
                "client_id": client_id,
                "agm_date": agm_date,
                "days_remaining": days_remaining,
                "status": status,
            })

        return api_response(True, {
            "agm_date": agm_date,
            "client_id": client_id,
            "calendar": calendar,
        })
    except Exception as e:
        _logger.exception("mca_calendar error")
        return api_response(False, None, "Unable to compute MCA calendar. Please try again.")


@router.get("/filing-history")
def filing_history(
    client_id: str = Query(...),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    current_user: dict = Depends(rbac("mca", "read")),
):
    """List filed MCA records with SRN and acknowledgement."""
    assert_client_access(current_user, client_id)
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
        return api_response(False, None, "Unable to complete MCA operation. Please try again.")
