"""
Universal activity log service.
Every major platform action should call log_activity().
"""
from typing import Optional
from datetime import datetime, timezone
import uuid


def log_activity(
    action: str,
    description: str,
    client_id: Optional[str] = None,
    actor_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """
    Create an activity log record.
    In production this would INSERT into the activity_logs table.
    Returns the record for use in API responses.
    """
    return {
        "id": str(uuid.uuid4()),
        "client_id": client_id,
        "actor_id": actor_id,
        "action": action,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "description": description,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
