"""
Audit trail service — immutable log of all sensitive mutations.
Covers: journal entries, invoices, compliance records, user role changes, client changes.
"""
import logging
from typing import Optional

_logger = logging.getLogger("caflow.audit")


def log_event(
    firm_id: str,
    entity_type: str,
    entity_id: str,
    action: str,
    actor_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    old_data: Optional[dict] = None,
    new_data: Optional[dict] = None,
    metadata: Optional[dict] = None,
) -> None:
    """
    Append an immutable audit event. Non-fatal — never raises.
    entity_type: 'journal_entry' | 'invoice' | 'compliance_record' | 'user_role' | 'client'
    action: 'create' | 'update' | 'delete' | 'status_change' | 'approve'
    """
    try:
        from core.supabase_client import get_service_supabase
        get_service_supabase().table("audit_log").insert({
            "firm_id": firm_id,
            "actor_id": actor_id,
            "actor_email": actor_email,
            "entity_type": entity_type,
            "entity_id": entity_id,
            "action": action,
            "old_data": old_data,
            "new_data": new_data,
            "metadata": metadata,
        }).execute()
    except Exception as e:
        _logger.error("audit_log insert failed: %s", e)
