"""
Audit trail service — immutable log of all sensitive mutations.
Covers: journal entries, invoices, compliance records, user role changes, client changes.

TODO(compliance): docs/compliance/06-data-protection-dpdp.md
    TWO THINGS ABOUT audit_log THAT A FUTURE CHANGE COULD BREAK WITHOUT NOTICING.

    1. THERE IS NO PURGE, AND THAT IS NOW LOAD-BEARING. DPDP Rule 6 requires
       logs of personal-data access to be kept AT LEAST ONE YEAR, in force from
       13-05-2027. Nothing sweeps this table today, so retention is unbounded
       and the floor is met by accident. Anyone adding a tidy-up here must keep
       a year, and should say so where they add it.

    2. THE ROWS CARRY FULL SNAPSHOTS, AND THEY CANNOT BE ERASED. Migration 111
       puts a trigger on every firm-scoped table and writes to_jsonb(NEW) /
       to_jsonb(OLD) — every column, including PAN, UAN, ESIC number, salary and
       bank account where the table has them. UPDATE and DELETE are blocked by
       trigger, so a DPDP erasure request cannot reach any of it, and nothing
       written can be taken back. Measured 2026-09-05: 1,469 of 46,311 rows
       already carried an identifier.

       The recommendation on file is to REDACT ON WRITE for the tables that
       carry identifiers — the log needs to show who changed what and when, not
       a column-wise copy of the row. Not done here because it trades against
       the audit trail's completeness and is an owner's decision. See §5a of the
       doc, and task #127.
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
