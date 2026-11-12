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

       DONE for the TRIGGER path, in migration 336: public.audit_redact
       replaces the VALUE of a person's government and financial identifiers
       and keeps the KEY, so the log still shows which field changed.

       NOT done here, and deliberately: of 893 rows this Python path has
       written, ZERO carried an identifier — it is called with small hand-built
       intent dicts, not row snapshots. Adding a redactor here would be a second
       implementation of one rule, for a case that does not occur. IF YOU EVER
       PASS A WHOLE ROW to old_data/new_data, that stops being true — redact it
       at the call site, or move the rule into one shared place and pin the two
       with a parity test, the way this codebase does elsewhere.
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


#: Columns an edit's audit row does not carry: they change on every save and say nothing the row's own timestamp does not.
_NOT_AN_EDIT = frozenset({"updated_at", "lines"})


def _json_safe(value):
    """The value as JSON would read it back (a date, a Decimal and a UUID as text), so a figure the route holds as a Python
    object cannot make the audit insert fail and, because `log_event` is non-fatal, vanish without a trace."""
    import json
    return json.loads(json.dumps(value, default=str))


def log_document_edit(
    firm_id: str,
    entity_type: str,
    entity_id: str,
    before: Optional[dict],
    written: dict,
    *,
    actor_id: Optional[str] = None,
    actor_email: Optional[str] = None,
    updated: Optional[dict] = None,
    matched: bool = True,
    old_lines: Optional[list] = None,
    new_lines: Optional[list] = None,
) -> None:
    """Record an edit of an invoice, a bill or a note WITH what it replaced (POST-A-424).

    THE APPLICATION'S OWN RECORD, written in every case and relied on for none. The six edit routes write through `privileged_for`,
    whose statements carry the signed-in member (`core/acting_client`, migration 547), so where the database receives that header the
    row-level capture records a whole-row before-and-after for the three older tables (`client_sales_invoices`, `credit_notes`,
    `purchase_bills`); the three newer notes (`debit_notes`, `sales_debit_notes`, `purchase_credit_notes`) have no capture trigger at
    all, and whether the header reaches the database in production is not yet verified. Before this the invoice and the bill logged
    the row AFTER the change and no `old_data`, and the four notes logged nothing. A note, a reference or a due date that was changed,
    and since POST-A-399 one that is CLEARED, therefore left a record of what it had been on some deployments and tables and none on
    others. `before` is the row as the route read it before writing; `written` is what it wrote; `old_data` is the previous value of
    each column written (a column the row did not carry is left out and never recorded as empty), `new_data` is what each now holds,
    and `metadata.changed` names the columns whose value is different. `matched` is whether the statement changed a row: an UPDATE
    that matched nothing records nothing, the rule `document_header_writer` keeps. A draft's lines are replaced as a whole and are
    recorded as a whole, both ways. Nothing is written when nothing was. Non-fatal like `log_event`, and the actor is the AUTH id
    (`audit_log.actor_id`)."""
    if not matched:
        return
    keys = [k for k in written if k not in _NOT_AN_EDIT]
    if not keys and old_lines is None:
        return
    row = before or {}
    now = updated or {}
    old = {k: row[k] for k in keys if k in row}
    new = {k: now.get(k, written[k]) for k in keys}
    changed = [k for k in old if old[k] != new.get(k)]
    if old_lines is not None:
        old["lines"] = old_lines
        new["lines"] = new_lines if new_lines is not None else []
        changed.append("lines")
    log_event(
        firm_id, entity_type, entity_id, "update", actor_id=actor_id, actor_email=actor_email,
        old_data=_json_safe(old) if old else None, new_data=_json_safe(new),
        metadata={"changed": changed, "recorded_by": "log_document_edit"},
    )

