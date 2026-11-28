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
import functools
import inspect
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


#: The keys whose VALUE is replaced in a record this module writes (POST-A-167). It is migration 336's `audit_redact` list, which the row-level
#: trigger applies to a table's snapshot; a record a ROUTE writes is not a trigger's and was never redacted, so the same keys are replaced here,
#: and `tests/test_the_audit_log_names_one_kind_of_actor.py`'s sibling `test_a_route_record_redacts_what_the_trigger_redacts` pins the two lists.
AUDIT_REDACT_KEYS = frozenset({
    "pan", "deductee_pan", "deductor_pan", "landlord_pan", "lender_pan", "vendor_pan", "aadhaar_last4", "uan", "bank_account_no",
    "account_number", "date_of_birth", "deductee_tin", "tax_identification_number",
})
REDACTED = "[redacted]"


def redact_identifiers(value):
    """`value` with the VALUE of each key in `AUDIT_REDACT_KEYS` replaced, at any depth, and the key kept (so the log still shows the field was
    written). A None stays None, as in the trigger: 'this was empty' is a fact."""
    if isinstance(value, dict):
        return {k: (value[k] if value[k] is None else REDACTED) if str(k).lower() in AUDIT_REDACT_KEYS else redact_identifiers(value[k])
                for k in value}
    if isinstance(value, list):
        return [redact_identifiers(v) for v in value]
    return value


def log_write(current_user: dict, entity_type: str, entity_id, action: str, *, client_id=None,
              new_data: Optional[dict] = None, old_data: Optional[dict] = None, metadata: Optional[dict] = None) -> None:
    """A route's record of who wrote a table the row-level audit trigger does not cover (POST-A-167).

    The firm and the person come from the caller (`current_user`), the person by the AUTH id because that is what `audit_log.actor_id` takes
    (`tests/test_the_audit_log_names_one_kind_of_actor.py`), so a route cannot name the wrong kind of id. The client the write was for is kept
    beside what was written, since the log is read one client at a time. Identifiers of a person are replaced (`redact_identifiers`), because
    nothing else does it for a record written here. Non-fatal like `log_event`: a failed audit insert is logged and the write stands, which is
    the same trade the rest of the log makes.
    """
    data = dict(new_data or {})
    if client_id is not None:
        data.setdefault("client_id", str(client_id))
    log_event(
        current_user.get("firm_id") or "", entity_type, str(entity_id or ""), action,
        actor_id=current_user.get("auth_user_id"), actor_email=current_user.get("email"),
        old_data=redact_identifiers(_json_safe(old_data)) if old_data else None,
        new_data=redact_identifiers(_json_safe(data)) if data else None, metadata=metadata,
    )


#: A text longer than this is a document or a pasted file, not a field: the record keeps its length and not its content.
_LONGEST_FIELD = 160


def _trim(value, depth: int = 0):
    """A request value as the audit row keeps it. A short scalar as it is; a long text as its length; a list or a nested record as a count of what
    it held, never its content (a pasted file, a computation, a JSON payload are not 'what was stated'; the rows they became are audited where
    they were written)."""
    if isinstance(value, str):
        return value if len(value) <= _LONGEST_FIELD else {"chars": len(value)}
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    if isinstance(value, dict):
        return {"keys": len(value)}
    if isinstance(value, (list, tuple, set)):
        return {"count": len(value)}
    return str(value)[:_LONGEST_FIELD]


_NOT_A_REQUEST_FIELD = frozenset({"current_user", "user", "request", "response", "background_tasks", "db", "file", "files"})
#: A request that carries one of these as true writes nothing: it is a preview or a dry run, and recording it would say a write happened.
_WRITES_NOTHING_WHEN = ("preview", "dry_run", "is_dry_run", "dryrun", "validate_only")


def _request_summary(kwargs: dict) -> dict:
    """What the caller sent a write route, kept short: every scalar parameter at the top, and the fields of each body model or dict under `body`
    (only the fields the caller SENT, nulls included, so a field that was cleared shows as cleared, and a field that took its default does not
    appear). A body field never overwrites a path or query parameter of the same name."""
    out: dict = {}
    body: dict = {}
    for name, value in kwargs.items():
        if name in _NOT_A_REQUEST_FIELD:
            continue
        dump = getattr(value, "model_dump", None)
        if callable(dump):
            body.update({k: _trim(v) for k, v in dump(mode="json", exclude_unset=True).items()})
        elif isinstance(value, dict):
            body.update({str(k): _trim(v) for k, v in value.items()})
        elif isinstance(value, (str, int, float, bool, list, tuple)) or value is None:
            out[name] = _trim(value)
    if body:
        out["body"] = body
    return out


def _path(data, dotted: str):
    cur = data
    for part in dotted.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _entity_id_of(kwargs: dict, data, id_in: tuple = ()) -> str:
    """The record's id: the route's own statement of where the answer carries it (`id_in`, a dotted path into the answer), else the answer's
    `id`, else the first path parameter that ends in `_id` (not the client, the firm or the user)."""
    for dotted in id_in:
        found = _path(data, dotted)
        if found:
            return str(found)
    if isinstance(data, dict) and data.get("id"):
        return str(data["id"])
    for name, value in kwargs.items():
        if name.endswith("_id") and name not in ("client_id", "firm_id", "user_id") and isinstance(value, (str, int)) and value != "":
            return str(value)
    return ""


def _flag_set(request: dict) -> bool:
    flat = {**request, **(request.get("body") or {})}
    return any(flat.get(k) is True for k in _WRITES_NOTHING_WHEN)


def _record_route_write(entity_type: str, action: str, kwargs: dict, result, id_in: tuple = (), wrote=None) -> None:
    """The event for a write route that finished: nothing if it answered a refusal or only previewed, one row if it answered success.
    `wrote(data)` lets a route say its own success wrote nothing (an apply that applied none)."""
    try:
        if isinstance(result, dict) and result.get("success") is False:
            return
        current_user = kwargs.get("current_user") if "current_user" in kwargs else kwargs.get("user")
        if not isinstance(current_user, dict):
            _logger.error("audited route has no current_user: %s %s", entity_type, action)
            return
        data = result.get("data") if isinstance(result, dict) else None
        request = _request_summary(kwargs)
        if _flag_set(request) or (wrote is not None and not wrote(data)):
            return
        client_id = request.get("client_id") or (request.get("body") or {}).get("client_id") or (data.get("client_id") if isinstance(data, dict) else None)
        log_write(current_user, entity_type, _entity_id_of(kwargs, data, id_in), action, client_id=client_id, new_data=request,
                  metadata={"recorded_by": "audited"})
    except Exception as e:  # noqa: BLE001 — the record must never undo the write it describes
        _logger.error("audited route could not record %s %s: %s", entity_type, action, e)


def audited(entity_type: str, action: str, *, id_in: tuple = (), wrote=None):
    """Mark a write route as recording who wrote (POST-A-167): after it answers success, one `audit_log` row names the firm, the person (by AUTH
    id), the kind of record, the action, the record's id, the client, and what the caller sent (scalars as sent, long texts and nested records as
    sizes, identifiers of a person replaced).

    This is the RECORD OF A STATEMENT, not a before-and-after: a route that must keep the old values (a document edit) calls `log_event` or
    `log_document_edit` itself with them. A route that answers `{"success": false}` or raises records nothing, and neither does one whose request
    is a preview or a dry run, or whose `wrote(data)` says its success changed nothing. `id_in` names where the ANSWER carries the record's id when
    that is not `data.id` (a dotted path: "filing.id"). The decorator goes BELOW the `@router.post(...)` line so the registered function is the
    wrapped one; `functools.wraps` keeps the signature FastAPI reads."""
    def decorate(fn):
        if inspect.iscoroutinefunction(fn):
            @functools.wraps(fn)
            async def wrapper(*args, **kwargs):
                result = await fn(*args, **kwargs)
                _record_route_write(entity_type, action, kwargs, result, id_in, wrote)
                return result
        else:
            @functools.wraps(fn)
            def wrapper(*args, **kwargs):
                result = fn(*args, **kwargs)
                _record_route_write(entity_type, action, kwargs, result, id_in, wrote)
                return result
        wrapper.__audited__ = (entity_type, action)
        return wrapper
    return decorate


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

