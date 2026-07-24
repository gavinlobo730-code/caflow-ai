from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from core.permissions import rbac
from core.authz import filter_by_client
from typing import Optional
from models.common import api_response
from repositories.reminders_repository import reminders_repo
from services.reminder_service import create_reminder, mark_sent

router = APIRouter(prefix="/api/reminders", tags=["reminders"])


class ReminderCreate(BaseModel):
    client_id: str
    reminder_type: str
    scheduled_for: str
    task_id: Optional[str] = None
    message: Optional[str] = None


@router.get("")
def list_reminders(
    client_id: Optional[str] = None,
    status: Optional[str] = None,
    current_user: dict = Depends(rbac("reminder", "read")),
):
    firm_id = current_user.get("firm_id")
    reminders = reminders_repo.find_all(firm_id=firm_id, client_id=client_id, status=status)
    reminders = filter_by_client(current_user, reminders)  # M2/M5: assignment scope
    return api_response(True, {"reminders": reminders, "total": len(reminders)})


@router.post("")
def create_reminder_endpoint(body: ReminderCreate, current_user: dict = Depends(rbac("reminder", "write"))):
    from core.authz import assert_client_access
    assert_client_access(current_user, body.client_id)  # M6 #7: body client_id guard
    firm_id = current_user.get("firm_id")
    reminder_data = create_reminder(
        client_id=body.client_id,
        reminder_type=body.reminder_type,
        scheduled_for=body.scheduled_for,
        task_id=body.task_id,
        message=body.message,
    )
    reminder = reminders_repo.create({**reminder_data, "firm_id": firm_id})
    return api_response(True, {"reminder": reminder})


@router.patch("/{reminder_id}/sent")
def mark_reminder_sent(reminder_id: str, current_user: dict = Depends(rbac("reminder", "write"))):
    firm_id = current_user.get("firm_id")
    reminder = reminders_repo.find_by_id(reminder_id)
    if not reminder:
        raise HTTPException(status_code=404, detail="Reminder not found")
    if reminder.get("firm_id") != firm_id:
        raise HTTPException(status_code=404, detail="Reminder not found")
    updates = mark_sent(reminder)
    updated = reminders_repo.update(reminder_id, updates)
    return api_response(True, {"reminder": updated})
