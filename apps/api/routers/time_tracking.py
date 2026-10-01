from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from models.common import api_response
from core.permissions import rbac
from core.authz import assert_client_access, can_access_client, effective_client_ids, filter_by_client
from repositories.time_tracking_repository import time_tracking_repo
from domain.billing import time_rate
from services import time_rates_service

router = APIRouter(prefix="/api/time-entries", tags=["time-tracking"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_duration(started_at: str, ended_at: str) -> int:
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    delta = end - start
    return max(0, int(delta.total_seconds() / 60))


def _worth(entry: dict) -> dict:
    """The rate an entry bills at and what its time is worth. `billable_rate_paise`
    first, the legacy `hourly_rate_paise` as the fallback it always was; None for
    both is "no rate", never 0. A non-billable or still-running entry has no value."""
    billable, hourly = entry.get("billable_rate_paise"), entry.get("hourly_rate_paise")
    rate = billable if billable is not None else hourly
    if not entry.get("is_billable"):
        return {"rate_paise": None, "value_paise": None}
    return {"rate_paise": time_rate.clean_rate(rate),
            "value_paise": time_rate.value_paise(entry.get("duration_minutes"), rate)
            if entry.get("ended_at") else None}


def _rate_answer(resolved: dict) -> dict:
    return {"source": resolved["rate_source"], "notes": resolved["notes"]}


def _assert_entry_scope(current_user: dict, entry: Optional[dict]) -> dict:
    """404 unless the entry exists in the caller's firm AND (when the entry
    carries a client_id — many don't, e.g. internal/admin work) the caller
    may access that client. can_access_client(user, None) is always True, so
    a client-less entry is unaffected. ONE fixed message for both the
    missing-row and hidden-client branches — mirrors year_end.py's
    _assert_engagement_scope.

    # M2 audit finding: stop_timer/update_entry/delete_entry resolved the
    # entry by firm_id alone and never checked its client against the
    # caller's assignment — an Executive/Reviewer/Manager could stop, edit
    # or delete another staff member's time entry against an assigned
    # client outside their own book.
    """
    if not entry or not can_access_client(current_user, entry.get("client_id")):
        raise HTTPException(status_code=404, detail="Time entry not found")
    return entry


class ManualEntryCreate(BaseModel):
    task_id: Optional[str] = None
    client_id: Optional[str] = None
    engagement_id: Optional[str] = None
    description: Optional[str] = None
    started_at: str
    ended_at: Optional[str] = None
    duration_minutes: Optional[int] = None
    is_billable: bool = True
    hourly_rate_paise: Optional[int] = None
    billable_rate_paise: Optional[int] = None   # Amd v1.1 FR-REV-07 (capture)


class StartTimerBody(BaseModel):
    task_id: Optional[str] = None
    client_id: Optional[str] = None
    # practice_management-11. Absent means "the client's single ACTIVE
    # engagement", and several active means none is chosen for you — see
    # domain/billing/time_rate.default_engagement.
    engagement_id: Optional[str] = None
    description: Optional[str] = None
    is_billable: bool = True


class EntryUpdate(BaseModel):
    description: Optional[str] = None
    is_billable: Optional[bool] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    duration_minutes: Optional[int] = None
    hourly_rate_paise: Optional[int] = None
    billable_rate_paise: Optional[int] = None   # Amd v1.1 FR-REV-07 (capture)
    # NOTE: is_billed / billed_invoice_id are intentionally NOT editable here —
    # they are system-controlled (billed_invoice_id is authoritative; is_billed is
    # a GENERATED column). See migration 078.


@router.get("")
def list_entries(
    user_id: Optional[str] = None,
    client_id: Optional[str] = None,
    task_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: dict = Depends(rbac("time_entry", "read")),
):
    firm_id = current_user.get("firm_id")
    entries = time_tracking_repo.find_all(
        firm_id=firm_id,
        user_id=user_id,
        client_id=client_id,
        task_id=task_id,
        date_from=date_from,
        date_to=date_to,
    )
    entries = filter_by_client(current_user, entries)  # M2/M5: assignment scope
    # What each entry is WORTH is the server's figure (minutes x rate / 60, whole
    # paise) and an entry with no rate says so: `value_paise` is null for it, which
    # is not zero. The screen used to multiply in the browser and print nothing at
    # all for an entry whose rate was missing.
    entries = [{**e, **_worth(e)} for e in entries]
    completed = [e for e in entries if e.get("duration_minutes")]
    total_minutes = sum(e["duration_minutes"] for e in completed)
    billable_minutes = sum(e["duration_minutes"] for e in completed if e.get("is_billable"))
    return api_response(True, {
        "entries": entries,
        "total": len(entries),
        "total_minutes": total_minutes,
        "billable_minutes": billable_minutes,
    })


@router.get("/export")
def export_entries(
    fmt: str = "csv",
    user_id: Optional[str] = None,
    client_id: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    current_user: dict = Depends(rbac("time_entry", "report")),
):
    """Export time entries as CSV or XLSX with user/client/date filters."""
    from fastapi.responses import Response
    from services.time_export_service import export_time_entries

    if fmt not in ("csv", "xlsx"):
        raise HTTPException(status_code=400, detail="fmt must be 'csv' or 'xlsx'")

    # M2 audit finding: this export had no assignment-scope filtering at
    # all (unlike list_entries's filter_by_client just above) — an
    # Executive/Reviewer/Manager could export another staff member's
    # unassigned client's billing data, or every client in the firm's, by
    # passing client_id (or omitting it) with no ownership check.
    firm_id = current_user.get("firm_id")
    content, filename, media_type = export_time_entries(
        firm_id=firm_id,
        fmt=fmt,
        user_id=user_id,
        client_id=client_id,
        date_from=date_from,
        date_to=date_to,
        effective_client_ids=effective_client_ids(current_user),
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/start")
def start_timer(body: StartTimerBody, current_user: dict = Depends(rbac("time_entry", "write"))):
    assert_client_access(current_user, body.client_id)
    firm_id = current_user.get("firm_id")
    user_id = current_user.get("id")

    # Stop any currently running timer first
    running = time_tracking_repo.find_running(firm_id=firm_id, user_id=user_id)
    if running:
        duration = _compute_duration(running["started_at"], _now())
        time_tracking_repo.update(running["id"], {"ended_at": _now(), "duration_minutes": duration})

    # The engagement and the rate are resolved NOW, so the row a running timer
    # lives in already says which engagement it is for and what an hour of it
    # bills at. A named engagement that is not this client's is refused (422)
    # before anything is written, and a stop re-resolves only a rate that is
    # still missing (see stop_timer).
    resolved = time_rates_service.resolve_for_entry(
        firm_id, user_id, body.client_id, body.engagement_id, is_billable=body.is_billable)
    entry = time_tracking_repo.create({
        "firm_id": firm_id,
        "user_id": user_id,
        "task_id": body.task_id,
        "client_id": body.client_id,
        "engagement_id": resolved["engagement_id"],
        "billable_rate_paise": resolved["billable_rate_paise"],
        "description": body.description,
        "started_at": _now(),
        "ended_at": None,
        "duration_minutes": None,
        "is_billable": body.is_billable,
    })
    return api_response(True, {"entry": entry, "rate": _rate_answer(resolved)})


@router.post("/{entry_id}/stop")
def stop_timer(entry_id: str, current_user: dict = Depends(rbac("time_entry", "write"))):
    firm_id = current_user.get("firm_id")
    entry = time_tracking_repo.find_by_id(entry_id, firm_id=firm_id)
    entry = _assert_entry_scope(current_user, entry)
    if entry.get("ended_at"):
        raise HTTPException(status_code=400, detail="Timer already stopped")

    now = _now()
    duration = _compute_duration(entry["started_at"], now)
    fields = {"ended_at": now, "duration_minutes": duration}
    # A rate that was missing when the timer started may have been recorded while
    # it ran: look again, once, and only for an entry that still has NONE. A rate
    # the entry already carries is never replaced here — it is the price the work
    # was started at, and re-pricing logged work behind somebody's back is the
    # thing storing the rate on the row exists to prevent.
    answer = {"source": None, "notes": []}
    if (entry.get("is_billable") and entry.get("billable_rate_paise") is None
            and entry.get("hourly_rate_paise") is None):
        resolved = time_rates_service.resolve_for_entry(
            firm_id, entry.get("user_id") or current_user.get("id"),
            entry.get("client_id"), entry.get("engagement_id"), is_billable=True)
        if resolved["billable_rate_paise"] is not None:
            fields["billable_rate_paise"] = resolved["billable_rate_paise"]
        answer = _rate_answer(resolved)
    updated = time_tracking_repo.update(entry_id, fields, firm_id=firm_id)
    return api_response(True, {"entry": updated, "rate": answer})


@router.post("")
def create_manual_entry(body: ManualEntryCreate, current_user: dict = Depends(rbac("time_entry", "write"))):
    assert_client_access(current_user, body.client_id)
    firm_id = current_user.get("firm_id")
    user_id = current_user.get("id")

    duration = body.duration_minutes
    if not duration and body.ended_at:
        duration = _compute_duration(body.started_at, body.ended_at)

    # A rate typed on the entry wins, then the engagement's, then the person's.
    # The Time screen's "Rate" box has always posted `hourly_rate_paise`, so that
    # is read as the entry's own rate when no `billable_rate_paise` is given; it is
    # still stored where it always was, because the analytics read it there.
    typed = body.billable_rate_paise if body.billable_rate_paise is not None else body.hourly_rate_paise
    resolved = time_rates_service.resolve_for_entry(
        firm_id, user_id, body.client_id, body.engagement_id,
        entry_rate=typed, is_billable=body.is_billable)
    entry = time_tracking_repo.create({
        "firm_id": firm_id,
        "user_id": user_id,
        "task_id": body.task_id,
        "client_id": body.client_id,
        "engagement_id": resolved["engagement_id"],
        "description": body.description,
        "started_at": body.started_at,
        "ended_at": body.ended_at,
        "duration_minutes": duration,
        "is_billable": body.is_billable,
        "hourly_rate_paise": body.hourly_rate_paise,
        "billable_rate_paise": resolved["billable_rate_paise"],
    })
    return api_response(True, {"entry": entry, "rate": _rate_answer(resolved)})


@router.patch("/{entry_id}")
def update_entry(entry_id: str, body: EntryUpdate, current_user: dict = Depends(rbac("time_entry", "write"))):
    firm_id = current_user.get("firm_id")
    entry = time_tracking_repo.find_by_id(entry_id, firm_id=firm_id)
    _assert_entry_scope(current_user, entry)

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "started_at" in updates and "ended_at" in updates:
        updates["duration_minutes"] = _compute_duration(updates["started_at"], updates["ended_at"])
    # A rate set on an entry is the way a "no rate" hour on the unbilled-work list
    # gets one, so it takes the same rule as every other door: whole non-negative
    # paise (the column CHECKs nothing — `time_entries` predates it), and never on
    # time an invoice has already been raised from, because the rate IS part of
    # what that invoice billed and changing it here would leave the invoice
    # describing work at a price it was not billed at.
    rate_fields = [f for f in ("billable_rate_paise", "hourly_rate_paise") if f in updates]
    if rate_fields and entry.get("billed_invoice_id"):
        raise HTTPException(
            status_code=409,
            detail="This time is already on an invoice, so its rate is part of what was "
                   "billed and cannot be changed here.")
    for f in rate_fields:
        updates[f] = time_rates_service.check_rate(updates[f])
    updated = time_tracking_repo.update(entry_id, updates, firm_id=firm_id)
    return api_response(True, {"entry": updated})


@router.delete("/{entry_id}")
def delete_entry(entry_id: str, current_user: dict = Depends(rbac("time_entry", "delete"))):
    firm_id = current_user.get("firm_id")
    entry = time_tracking_repo.find_by_id(entry_id, firm_id=firm_id)
    _assert_entry_scope(current_user, entry)
    time_tracking_repo.delete(entry_id, firm_id=firm_id)
    return api_response(True, {"deleted": True})


@router.get("/summary/me")
def my_summary(
    period: str = "week",
    current_user: dict = Depends(rbac("time_entry", "read")),
):
    firm_id = current_user.get("firm_id")
    user_id = current_user.get("id")
    summary = time_tracking_repo.get_summary(firm_id=firm_id, user_id=user_id)
    return api_response(True, summary)


@router.get("/engagement-choices")
def engagement_choices(client_id: str,
                       current_user: dict = Depends(rbac("time_entry", "read"))):
    """The engagements a time entry for this client may be recorded against, and
    the one it defaults to (the client's single active engagement). The billing
    rate OVERRIDE is not served — it is fee economics, `billing:write`."""
    assert_client_access(current_user, client_id)
    return api_response(True, time_rates_service.engagement_choices(
        current_user.get("firm_id"), client_id))


@router.get("/running/me")
def get_running_timer(current_user: dict = Depends(rbac("time_entry", "read"))):
    firm_id = current_user.get("firm_id")
    user_id = current_user.get("id")
    running = time_tracking_repo.find_running(firm_id=firm_id, user_id=user_id)
    return api_response(True, {"running": running})
