from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
from models.common import api_response
from core.permissions import rbac
from repositories.time_tracking_repository import time_tracking_repo

router = APIRouter(prefix="/api/time-entries", tags=["time-tracking"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _compute_duration(started_at: str, ended_at: str) -> int:
    start = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    end = datetime.fromisoformat(ended_at.replace("Z", "+00:00"))
    delta = end - start
    return max(0, int(delta.total_seconds() / 60))


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

    firm_id = current_user.get("firm_id")
    content, filename, media_type = export_time_entries(
        firm_id=firm_id,
        fmt=fmt,
        user_id=user_id,
        client_id=client_id,
        date_from=date_from,
        date_to=date_to,
    )
    return Response(
        content=content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.post("/start")
def start_timer(body: StartTimerBody, current_user: dict = Depends(rbac("time_entry", "write"))):
    firm_id = current_user.get("firm_id")
    user_id = current_user.get("id")

    # Stop any currently running timer first
    running = time_tracking_repo.find_running(firm_id=firm_id, user_id=user_id)
    if running:
        duration = _compute_duration(running["started_at"], _now())
        time_tracking_repo.update(running["id"], {"ended_at": _now(), "duration_minutes": duration})

    entry = time_tracking_repo.create({
        "firm_id": firm_id,
        "user_id": user_id,
        "task_id": body.task_id,
        "client_id": body.client_id,
        "description": body.description,
        "started_at": _now(),
        "ended_at": None,
        "duration_minutes": None,
        "is_billable": body.is_billable,
    })
    return api_response(True, {"entry": entry})


@router.post("/{entry_id}/stop")
def stop_timer(entry_id: str, current_user: dict = Depends(rbac("time_entry", "write"))):
    entry = time_tracking_repo.find_by_id(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Time entry not found")
    if entry.get("ended_at"):
        raise HTTPException(status_code=400, detail="Timer already stopped")

    now = _now()
    duration = _compute_duration(entry["started_at"], now)
    updated = time_tracking_repo.update(entry_id, {"ended_at": now, "duration_minutes": duration})
    return api_response(True, {"entry": updated})


@router.post("")
def create_manual_entry(body: ManualEntryCreate, current_user: dict = Depends(rbac("time_entry", "write"))):
    firm_id = current_user.get("firm_id")
    user_id = current_user.get("id")

    duration = body.duration_minutes
    if not duration and body.ended_at:
        duration = _compute_duration(body.started_at, body.ended_at)

    entry = time_tracking_repo.create({
        "firm_id": firm_id,
        "user_id": user_id,
        "task_id": body.task_id,
        "client_id": body.client_id,
        "engagement_id": body.engagement_id,
        "description": body.description,
        "started_at": body.started_at,
        "ended_at": body.ended_at,
        "duration_minutes": duration,
        "is_billable": body.is_billable,
        "hourly_rate_paise": body.hourly_rate_paise,
        "billable_rate_paise": body.billable_rate_paise,
    })
    return api_response(True, {"entry": entry})


@router.patch("/{entry_id}")
def update_entry(entry_id: str, body: EntryUpdate, current_user: dict = Depends(rbac("time_entry", "write"))):
    entry = time_tracking_repo.find_by_id(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Time entry not found")

    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if "started_at" in updates and "ended_at" in updates:
        updates["duration_minutes"] = _compute_duration(updates["started_at"], updates["ended_at"])
    updated = time_tracking_repo.update(entry_id, updates)
    return api_response(True, {"entry": updated})


@router.delete("/{entry_id}")
def delete_entry(entry_id: str, current_user: dict = Depends(rbac("time_entry", "delete"))):
    entry = time_tracking_repo.find_by_id(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Time entry not found")
    time_tracking_repo.delete(entry_id)
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


@router.get("/running/me")
def get_running_timer(current_user: dict = Depends(rbac("time_entry", "read"))):
    firm_id = current_user.get("firm_id")
    user_id = current_user.get("id")
    running = time_tracking_repo.find_running(firm_id=firm_id, user_id=user_id)
    return api_response(True, {"running": running})
