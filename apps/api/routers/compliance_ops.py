"""
Compliance Operations router (Phase 4.4) — the operational layer over the
canonical obligation entity (compliance_records): generation, assignment,
lifecycle transitions, the Practice → Compliance dashboard, the calendar
projection, and internal escalations.

Thin surface over services/compliance_obligation_service.py + the existing
compliance_record_service. Distinct paths from routers/compliance.py (which owns
/tasks, /calendar, /seed). Never files anything; escalations are internal only.
"""
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel

from models.common import api_response
from core.permissions import rbac
from core.exceptions import ValidationError, NotFoundError
from services import compliance_obligation_service as obligations
from domain.compliance_record_service import compliance_record_service

router = APIRouter(prefix="/api/compliance", tags=["compliance_ops"])


class AssignBody(BaseModel):
    preparer_id: Optional[str] = None
    reviewer_id: Optional[str] = None
    approver_id: Optional[str] = None


class TransitionBody(BaseModel):
    status: str


@router.get("/obligations")
def list_obligations(client_id: Optional[str] = Query(None),
                     status: Optional[str] = Query(None),
                     compliance_type: Optional[str] = Query(None),
                     current_user: dict = Depends(rbac("compliance", "read"))):
    """List compliance obligations (canonical compliance_records), with risk scores."""
    rows = compliance_record_service.list_records(
        firm_id=current_user["firm_id"], client_id=client_id,
        status=status, compliance_type=compliance_type)
    return api_response(True, {"obligations": rows, "total": len(rows)})


@router.post("/obligations/generate")
def generate_obligations(client_id: Optional[str] = Query(None),
                         financial_year: Optional[str] = Query(None),
                         current_user: dict = Depends(rbac("compliance", "write"))):
    """Generate obligations for active engagements (idempotent). Draft obligations
    only — never files. Runs the same logic the daily scheduler uses."""
    return api_response(True, obligations.generate_due(
        current_user["firm_id"], client_id=client_id, financial_year=financial_year, actor=current_user))


@router.post("/obligations/{record_id}/assign")
def assign_obligation(record_id: str, body: AssignBody,
                      current_user: dict = Depends(rbac("compliance", "write"))):
    """Set preparer / reviewer / approver on an obligation (audited + timelined)."""
    return api_response(True, obligations.assign(
        current_user["firm_id"], record_id, preparer_id=body.preparer_id,
        reviewer_id=body.reviewer_id, approver_id=body.approver_id, actor=current_user))


@router.post("/obligations/{record_id}/transition")
def transition_obligation(record_id: str, body: TransitionBody,
                          current_user: dict = Depends(rbac("compliance", "write"))):
    """Advance an obligation through its lifecycle (validated; invalid transitions rejected)."""
    try:
        updated = obligations.transition(current_user["firm_id"], record_id, body.status, actor=current_user)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Compliance obligation not found.")
    return api_response(True, {"obligation": updated})


@router.get("/dashboard")
def compliance_dashboard(current_user: dict = Depends(rbac("compliance", "read"))):
    """Practice → Compliance dashboard: summary + workload by staff + workload by
    client + the obligation queue."""
    return api_response(True, obligations.dashboard(current_user["firm_id"]))


@router.get("/obligations/calendar")
def obligations_calendar(client_id: Optional[str] = Query(None),
                         current_user: dict = Depends(rbac("compliance", "read"))):
    """Calendar projection (upcoming / overdue / completed) over the canonical obligations."""
    return api_response(True, obligations.calendar(current_user["firm_id"], client_id=client_id))


@router.post("/run-escalations")
def run_escalations(current_user: dict = Depends(rbac("compliance", "write"))):
    """Manually run compliance escalations now (7/3/1-day + overdue; internal only).
    Same job the daily scheduler runs — works whether the scheduler is on or off."""
    return api_response(True, obligations.escalate(current_user["firm_id"], actor=current_user))
