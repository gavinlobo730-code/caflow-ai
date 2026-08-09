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
from core.authz import filter_by_client, assert_client_access, effective_client_ids
from core.exceptions import ValidationError, NotFoundError
from services import compliance_obligation_service as obligations
from domain.compliance_record_service import compliance_record_service

router = APIRouter(prefix="/api/compliance", tags=["compliance_ops"])


def _assert_obligation_scope(current_user: dict, record_id: str) -> dict:
    """Resolve a compliance_records row and 404 unless it belongs to the
    caller's firm and the caller may access its client.

    Sweep finding: assign/transition/mark-filed all called the domain
    service (compliance_record_service.get_record / update_record /
    mark_filed) directly, which only checks firm_id. routers/
    compliance_records.py resolves the SAME table and additionally calls
    assert_client_access at its own call sites before ever touching
    update_record — the identical resource guarded in one caller and not
    the other. This mirrors that call site rather than pushing the check
    into the shared domain service, so compliance_records.py's own
    (independent) checks are untouched."""
    try:
        rec = compliance_record_service.get_record(record_id, firm_id=current_user["firm_id"])
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Compliance obligation not found.")
    assert_client_access(current_user, rec.get("client_id"))
    return rec


class AssignBody(BaseModel):
    preparer_id: Optional[str] = None
    reviewer_id: Optional[str] = None
    approver_id: Optional[str] = None


class TransitionBody(BaseModel):
    status: str


class MarkFiledBody(BaseModel):
    acknowledgement_no: Optional[str] = None


@router.get("/obligations")
def list_obligations(client_id: Optional[str] = Query(None),
                     status: Optional[str] = Query(None),
                     compliance_type: Optional[str] = Query(None),
                     current_user: dict = Depends(rbac("compliance", "read"))):
    """List compliance obligations (canonical compliance_records), with risk scores.
    Assignment-scoped: non firm-wide roles see only obligations for their assigned
    clients (M2/M5), mirroring routers/compliance.py."""
    rows = compliance_record_service.list_records(
        firm_id=current_user["firm_id"], client_id=client_id,
        status=status, compliance_type=compliance_type)
    rows = filter_by_client(current_user, rows)   # M2/M5: assignment scope
    return api_response(True, {"obligations": rows, "total": len(rows)})


@router.post("/obligations/generate")
def generate_obligations(client_id: Optional[str] = Query(None),
                         financial_year: Optional[str] = Query(None),
                         current_user: dict = Depends(rbac("compliance", "write"))):
    """Generate obligations for active engagements (idempotent). Draft obligations
    only — never files. Runs the same logic the daily scheduler uses.

    Sweep finding: a named client_id was never checked against the caller's
    assignment; an omitted client_id ran the WHOLE FIRM'S generation
    (compliance.write is Executive+, not firm-wide-only). A named client is
    asserted directly; an omitted one is confined via allowed_client_ids —
    the same recurring_invoices.py "/run" shape, not a blanket 403, since a
    partial per-caller run is an honest answer here."""
    if client_id:
        assert_client_access(current_user, client_id)
    return api_response(True, obligations.generate_due(
        current_user["firm_id"], client_id=client_id, financial_year=financial_year, actor=current_user,
        allowed_client_ids=effective_client_ids(current_user)))


@router.post("/obligations/{record_id}/assign")
def assign_obligation(record_id: str, body: AssignBody,
                      current_user: dict = Depends(rbac("compliance", "write"))):
    """Set preparer / reviewer / approver on an obligation (audited + timelined)."""
    _assert_obligation_scope(current_user, record_id)
    return api_response(True, obligations.assign(
        current_user["firm_id"], record_id, preparer_id=body.preparer_id,
        reviewer_id=body.reviewer_id, approver_id=body.approver_id, actor=current_user))


@router.post("/obligations/{record_id}/transition")
def transition_obligation(record_id: str, body: TransitionBody,
                          current_user: dict = Depends(rbac("compliance", "write"))):
    """Advance an obligation through its lifecycle (validated; invalid transitions rejected)."""
    _assert_obligation_scope(current_user, record_id)
    try:
        updated = obligations.transition(current_user["firm_id"], record_id, body.status, actor=current_user)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Compliance obligation not found.")
    return api_response(True, {"obligation": updated})


@router.post("/obligations/{record_id}/mark-filed")
def mark_filed_obligation(record_id: str, body: MarkFiledBody,
                          current_user: dict = Depends(rbac("compliance", "write"))):
    """R3.13e — one-click "mark as filed" for callers migrating off the
    simple pending/filed model of compliance_calendar: walks the real
    multi-step workflow's shortest valid path to Filed rather than requiring
    the caller to step through it manually. Optionally records an ARN /
    acknowledgement number in the same call."""
    _assert_obligation_scope(current_user, record_id)
    try:
        updated = compliance_record_service.mark_filed(
            record_id, firm_id=current_user["firm_id"], actor=current_user,
            acknowledgement_no=body.acknowledgement_no)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Compliance obligation not found.")
    return api_response(True, {"obligation": updated})


@router.get("/dashboard")
def compliance_dashboard(current_user: dict = Depends(rbac("compliance", "read"))):
    """Practice → Compliance dashboard: summary + workload by staff + workload by
    client + the obligation queue.

    Sweep finding: unlike the tasks/lifecycle "aggregate counts only"
    dashboards left deliberately unscoped, this one returns the raw `queue`
    of obligation rows and a named `by_client` breakdown — real per-client
    data, not a cardinality signal. Narrowed via allowed_client_ids."""
    return api_response(True, obligations.dashboard(
        current_user["firm_id"], allowed_client_ids=effective_client_ids(current_user)))


@router.get("/obligations/calendar")
def obligations_calendar(client_id: Optional[str] = Query(None),
                         current_user: dict = Depends(rbac("compliance", "read"))):
    """Calendar projection (upcoming / overdue / completed) over the canonical obligations.
    Assignment-scoped per bucket (M2/M5), mirroring routers/compliance.py."""
    cal = obligations.calendar(current_user["firm_id"], client_id=client_id)
    cal = {bucket: filter_by_client(current_user, rows) for bucket, rows in cal.items()}
    return api_response(True, cal)


@router.post("/run-escalations")
def run_escalations(current_user: dict = Depends(rbac("compliance", "write"))):
    """Manually run compliance escalations now (7/3/1-day + overdue; internal only).
    Same job the daily scheduler runs — works whether the scheduler is on or off.

    Sweep finding: escalate() walked every open obligation in the FIRM with
    no assignment check (compliance.write is Executive+, not firm-wide-only).
    Confined via allowed_client_ids rather than a blanket 403 — escalating
    only one's own assigned clients is a complete, honest partial run, the
    same reasoning as generate_obligations above."""
    return api_response(True, obligations.escalate(
        current_user["firm_id"], actor=current_user,
        allowed_client_ids=effective_client_ids(current_user)))
