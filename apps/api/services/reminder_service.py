"""
Reminder service — infrastructure only.
Do NOT send actual WhatsApp or email messages from this service.
Future integrations will call send_whatsapp() and send_email() here.
"""
import uuid
from datetime import datetime, timezone
from typing import Optional


def create_reminder(
    client_id: str,
    reminder_type: str,
    scheduled_for: str,
    task_id: Optional[str] = None,
    message: Optional[str] = None,
) -> dict:
    """Create a reminder record. Does not send anything."""
    assert reminder_type in ("email", "whatsapp", "system"), \
        f"Invalid reminder_type: {reminder_type}"
    return {
        "id": str(uuid.uuid4()),
        "task_id": task_id,
        "client_id": client_id,
        "reminder_type": reminder_type,
        "scheduled_for": scheduled_for,
        "sent_at": None,
        "status": "pending",
        "message": message,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def schedule_reminder(reminder: dict, scheduled_for: str) -> dict:
    """Update the scheduled_for time of a pending reminder."""
    assert reminder["status"] == "pending", "Only pending reminders can be rescheduled"
    return {**reminder, "scheduled_for": scheduled_for,
            "updated_at": datetime.now(timezone.utc).isoformat()}


def mark_sent(reminder: dict) -> dict:
    """Mark a reminder as sent. Call after actual delivery is confirmed."""
    now = datetime.now(timezone.utc).isoformat()
    return {**reminder, "status": "sent", "sent_at": now, "updated_at": now}


def mark_failed(reminder: dict, reason: Optional[str] = None) -> dict:
    """Mark a reminder as failed."""
    now = datetime.now(timezone.utc).isoformat()
    msg = f"{reminder.get('message', '')} [FAILED: {reason}]" if reason else reminder.get("message")
    return {**reminder, "status": "failed", "message": msg, "updated_at": now}
