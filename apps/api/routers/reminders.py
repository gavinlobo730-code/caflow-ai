from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from models.common import api_response
from mock_data import MOCK_REMINDERS
from services.reminder_service import create_reminder, mark_sent, mark_failed

router = APIRouter(prefix="/api/reminders", tags=["reminders"])

REMINDER_STORE = list(MOCK_REMINDERS)


class ReminderCreate(BaseModel):
    client_id: str
    reminder_type: str
    scheduled_for: str
    task_id: Optional[str] = None
    message: Optional[str] = None


@router.get("")
def list_reminders(client_id: Optional[str] = None, status: Optional[str] = None):
    reminders = REMINDER_STORE
    if client_id:
        reminders = [r for r in reminders if r.get("client_id") == client_id]
    if status:
        reminders = [r for r in reminders if r["status"] == status]
    return api_response(True, {"reminders": reminders, "total": len(reminders)})


@router.post("")
def create_reminder_endpoint(body: ReminderCreate):
    reminder = create_reminder(
        client_id=body.client_id,
        reminder_type=body.reminder_type,
        scheduled_for=body.scheduled_for,
        task_id=body.task_id,
        message=body.message,
    )
    REMINDER_STORE.append(reminder)
    return api_response(True, {"reminder": reminder})


@router.patch("/{reminder_id}/sent")
def mark_reminder_sent(reminder_id: str):
    reminder = next((r for r in REMINDER_STORE if r["id"] == reminder_id), None)
    if not reminder:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Reminder not found")
    updated = mark_sent(reminder)
    reminder.update(updated)
    return api_response(True, {"reminder": reminder})
