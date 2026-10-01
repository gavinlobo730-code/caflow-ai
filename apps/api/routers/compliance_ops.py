"""
Compliance Operations router (Phase 4.4) — the operational layer over the
canonical obligation entity (compliance_records): generation, assignment,
lifecycle transitions, the Practice → Compliance dashboard, the calendar
projection, and internal escalations.

Thin surface over services/compliance_obligation_service.py + the existing
compliance_record_service. Distinct paths from routers/compliance.py (which owns
/tasks, /calendar, /seed). Never files anything; escalations are internal only.
"""
from datetime import date, timedelta
from typing import Annotated, Optional
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from pydantic import BaseModel, field_validator

from models.common import api_response
from core.permissions import rbac
from core.authz import filter_by_client, assert_client_access, effective_client_ids
from core.exceptions import ValidationError, NotFoundError
from services import compliance_obligation_service as obligations
from domain.compliance_record_service import clean_filed_date, compliance_record_service
from models.fy import OptionalFYLabel

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


def _a_filing_date(v: Optional[str]) -> Optional[str]:
    """A date somebody typed, or nothing. Absent stays absent — whether it is
    REQUIRED depends on the obligation (a GSTR-1/3B closes a period and needs it)
    and only the service knows the obligation."""
    return None if v in (None, "") else clean_filed_date(v)


class TransitionBody(BaseModel):
    status: str
    # Read only on the move to Filed. See compliance_obligation_service.transition.
    filed_date: Optional[str] = None
    acknowledgement_no: Optional[str] = None

    _date = field_validator("filed_date")(lambda cls, v: _a_filing_date(v))


class MarkFiledBody(BaseModel):
    acknowledgement_no: Optional[str] = None
    # REQUIRED (422 from the service) for a GSTR-1 or GSTR-3B, which closes its
    # period; optional for every other obligation, where today is recorded.
    filed_date: Optional[str] = None

    _date = field_validator("filed_date")(lambda cls, v: _a_filing_date(v))


def _filing_fields(updated: dict) -> dict:
    """What the caller must be able to see about whether the period closed.

    The same four keys `PATCH /calendar/{id}/filed` answers, for the same
    reason: a tick that locked nothing has to say so. Popped off the obligation
    because it is a property of the act of filing, not a column of the row."""
    lock = updated.pop("filing_lock", None)
    if lock is None:
        return {}
    return {
        "filing_recorded": lock["recorded"],
        "filing_not_recorded_reason": lock["reason"],
        "period_locked_from": lock["locked_from"],
        "period_locked_to": lock["locked_to"],
    }


class GenerateBody(BaseModel):
    """The same two values /obligations/generate takes as query parameters.

    They were query-only, so a caller that sent them in the JSON body — which
    is the natural shape for a POST, and what the foreign-vendor walkthrough
    sent — had them SILENTLY IGNORED and got the current financial year's
    obligations for the whole firm instead of the year and client it asked
    for. Nothing in the response said so; the response even names the FY it
    used, which read as confirmation.
    """
    client_id: Optional[str] = None
    financial_year: OptionalFYLabel = None


def _one_of(name: str, from_query: Optional[str], from_body: Optional[str]) -> Optional[str]:
    """The value a caller gave, whether they put it in the query or the body.

    Refuses rather than picking when both are present and differ: a caller who
    sent two different financial years has a bug, and choosing one for them
    hides it behind a plausible answer."""
    if from_query is not None and from_body is not None and from_query != from_body:
        raise HTTPException(
            status_code=422,
            detail=(f"{name} was sent twice with different values "
                    f"({from_query!r} in the query, {from_body!r} in the body). "
                    f"Send it once."))
    return from_query if from_query is not None else from_body


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
                         financial_year: Annotated[OptionalFYLabel, Query()] = None,
                         body: Optional[GenerateBody] = None,
                         current_user: dict = Depends(rbac("compliance", "write"))):
    """Generate obligations for active engagements (idempotent). Draft obligations
    only — never files. Runs the same logic the daily scheduler uses.

    Sweep finding: a named client_id was never checked against the caller's
    assignment; an omitted client_id ran the WHOLE FIRM'S generation
    (compliance.write is Executive+, not firm-wide-only). A named client is
    asserted directly; an omitted one is confined via allowed_client_ids —
    the same recurring_invoices.py "/run" shape, not a blanket 403, since a
    partial per-caller run is an honest answer here."""
    # Query parameter or JSON body — either is honoured, and the two are only
    # allowed to disagree by one of them being absent. Silently preferring one
    # is how a caller ends up generating a year it did not ask for.
    client_id = _one_of("client_id", client_id, body.client_id if body else None)
    # Both are OptionalFYLabel, so FastAPI has already refused a label that is
    # not a financial year and canonicalised the rest before this runs. That
    # also means '2025-2026' in the query and '2025-26' in the body arrive
    # equal, and are correctly NOT reported as a disagreement.
    financial_year = _one_of("financial_year", financial_year,
                             body.financial_year if body else None)

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
        updated = obligations.transition(
            current_user["firm_id"], record_id, body.status, actor=current_user,
            filed_date=body.filed_date, acknowledgement_no=body.acknowledgement_no)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Compliance obligation not found.")
    return api_response(True, {"obligation": updated, **_filing_fields(updated)})


@router.post("/obligations/{record_id}/mark-filed")
def mark_filed_obligation(record_id: str, body: MarkFiledBody,
                          current_user: dict = Depends(rbac("compliance", "write"))):
    """R3.13e — one-click "mark as filed" for callers migrating off the
    simple pending/filed model of compliance_calendar: walks the real
    multi-step workflow's shortest valid path to Filed rather than requiring
    the caller to step through it manually. Optionally records an ARN /
    acknowledgement number in the same call.

    For a GSTR-1 or GSTR-3B this is also what CLOSES THE PERIOD: the filing is
    written to `public.filings`, the only table the period lock reads, so the
    books inside the return's own window stop moving — and `filed_date` is
    required, because the lock message quotes it. The answer says whether a
    period was locked and, where none was, why not."""
    _assert_obligation_scope(current_user, record_id)
    try:
        updated = compliance_record_service.mark_filed(
            record_id, firm_id=current_user["firm_id"], actor=current_user,
            acknowledgement_no=body.acknowledgement_no, filed_date=body.filed_date)
    except NotFoundError:
        raise HTTPException(status_code=404, detail="Compliance obligation not found.")
    except ValidationError as e:
        # mark_filed fast-forwards through update_record, which is where
        # apex-overview-practice-02's period-end check lives (a return whose
        # own period has not ended yet cannot be walked to Filed here either).
        raise HTTPException(status_code=422, detail=str(e))
    return api_response(True, {"obligation": updated, **_filing_fields(updated)})


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


#: The widest window one calendar read may ask for. A month grid needs about 42
#: days; a year is generous, and an unbounded window is the read this parameter
#: exists to avoid (the answer must be proportional to what is on the screen).
MAX_CALENDAR_WINDOW_DAYS = 400


@router.get("/obligations/calendar")
def obligations_calendar(client_id: Optional[str] = Query(None),
                         # Annotated, so a caller that invokes the handler directly (the
                         # existing router-level tests do) gets a real None and not a
                         # `Query` object that fails the comparison below.
                         date_from: Annotated[Optional[date], Query()] = None,
                         date_to: Annotated[Optional[date], Query()] = None,
                         current_user: dict = Depends(rbac("compliance", "read"))):
    """Calendar projection (upcoming / overdue / completed) over the canonical obligations.
    Assignment-scoped per bucket (M2/M5), mirroring routers/compliance.py.

    `date_from` / `date_to` bound upcoming and completed by due date, both
    inclusive; the OVERDUE bucket is never bounded (see `obligations.calendar`).
    Giving one without the other, a window that ends before it starts, or one wider
    than a year is refused rather than answered with something else — a calendar
    that quietly widened or narrowed the window would show a month that is not the
    one asked for."""
    if (date_from is None) != (date_to is None):
        raise HTTPException(status_code=422,
                            detail="Give both date_from and date_to, or neither.")
    if date_from is not None and date_to is not None:
        if date_to < date_from:
            raise HTTPException(status_code=422, detail="date_to is before date_from.")
        if (date_to - date_from) > timedelta(days=MAX_CALENDAR_WINDOW_DAYS):
            raise HTTPException(
                status_code=422,
                detail=f"A calendar window is at most {MAX_CALENDAR_WINDOW_DAYS} days.")
    cal = obligations.calendar(current_user["firm_id"], client_id=client_id,
                               date_from=date_from, date_to=date_to)
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
