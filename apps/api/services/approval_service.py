"""
Module 9.0 / M4 — Governance approval engine (maker-checker).

A maker submits an approval_request for a sensitive action; a Partner (checker)
approves or rejects. On approval the registered handler executes the real
mutation via existing repositories/services (no duplicated business logic). Every
transition is mirrored to the immutable audit_log.

Request types (handlers execute against existing server paths):
  user_create / user_activation / role_change        -> user_repo
  assignment_create / assignment_remove / assignment_transfer -> assignment_repo
  coa_create / coa_update / coa_delete (archive)      -> accounting_service
"""
from typing import Callable, Optional

from fastapi import HTTPException

from repositories.approval_repository import approval_repo
from services.audit_service import log_event

_CANONICAL_ROLES = {"Partner", "Manager", "Executive", "Reviewer", "Client"}


# ── Execution handlers (run on approval) ─────────────────────────────────────

def _h_user_create(firm_id: str, p: dict) -> dict:
    from repositories.user_repository import user_repo
    if p.get("role") not in _CANONICAL_ROLES:
        raise HTTPException(400, "Invalid role")
    return user_repo.create({
        "firm_id": firm_id, "full_name": p.get("full_name"), "email": p.get("email"),
        "role": p["role"], "is_active": bool(p.get("is_active", True)),
    }) or {}


def _h_user_activation(firm_id: str, p: dict) -> dict:
    from repositories.user_repository import user_repo
    return user_repo.update(p["user_id"], {"is_active": bool(p["is_active"])}) or {}


def _h_role_change(firm_id: str, p: dict) -> dict:
    from repositories.user_repository import user_repo
    if p.get("role") not in _CANONICAL_ROLES:
        raise HTTPException(400, "Invalid role")
    return user_repo.update(p["user_id"], {"role": p["role"]}) or {}


def _h_assignment_create(firm_id: str, p: dict) -> dict:
    from repositories.assignment_repository import assignment_repo
    return assignment_repo.create(firm_id, p["user_id"], p["client_id"])


def _h_assignment_remove(firm_id: str, p: dict) -> dict:
    from repositories.assignment_repository import assignment_repo
    return {"removed": assignment_repo.remove(firm_id, p["user_id"], p["client_id"])}


def _h_assignment_transfer(firm_id: str, p: dict) -> dict:
    from repositories.assignment_repository import assignment_repo
    assignment_repo.remove(firm_id, p["from_user_id"], p["client_id"])
    created = assignment_repo.create(firm_id, p["to_user_id"], p["client_id"])
    return {"transferred": True, "assignment": created}


def _h_coa_create(firm_id: str, p: dict) -> dict:
    from domain.accounting_service import accounting_service
    return accounting_service.create_account(p)


def _h_coa_update(firm_id: str, p: dict) -> dict:
    from domain.accounting_service import accounting_service
    fields = {k: v for k, v in p.items() if k != "account_id"}
    return accounting_service.update_account(p["account_id"], fields)


def _h_coa_delete(firm_id: str, p: dict) -> dict:
    # Accounts are archived, never hard-deleted, for financial-record integrity.
    from domain.accounting_service import accounting_service
    return accounting_service.update_account(p["account_id"], {"is_active": False})


# type -> (required payload keys, summary builder, handler)
_SPECS: dict[str, dict] = {
    "user_create":        {"required": ["full_name", "email", "role"],
                           "summary": lambda p: f"Create user {p.get('email')} as {p.get('role')}",
                           "handler": _h_user_create},
    "user_activation":    {"required": ["user_id", "is_active"],
                           "summary": lambda p: f"{'Activate' if p.get('is_active') else 'Deactivate'} user {p.get('user_id')}",
                           "handler": _h_user_activation},
    "role_change":        {"required": ["user_id", "role"],
                           "summary": lambda p: f"Change role of {p.get('user_id')} to {p.get('role')}",
                           "handler": _h_role_change},
    "assignment_create":  {"required": ["user_id", "client_id"],
                           "summary": lambda p: f"Assign client {p.get('client_id')} to {p.get('user_id')}",
                           "handler": _h_assignment_create},
    "assignment_remove":  {"required": ["user_id", "client_id"],
                           "summary": lambda p: f"Remove client {p.get('client_id')} from {p.get('user_id')}",
                           "handler": _h_assignment_remove},
    "assignment_transfer": {"required": ["from_user_id", "to_user_id", "client_id"],
                           "summary": lambda p: f"Transfer client {p.get('client_id')} from {p.get('from_user_id')} to {p.get('to_user_id')}",
                           "handler": _h_assignment_transfer},
    "coa_create":         {"required": ["account_name", "account_type"],
                           "summary": lambda p: f"Create account {p.get('account_name')} ({p.get('account_type')})",
                           "handler": _h_coa_create},
    "coa_update":         {"required": ["account_id"],
                           "summary": lambda p: f"Update account {p.get('account_id')}",
                           "handler": _h_coa_update},
    "coa_delete":         {"required": ["account_id"],
                           "summary": lambda p: f"Archive account {p.get('account_id')}",
                           "handler": _h_coa_delete},
}

REQUEST_TYPES = tuple(_SPECS.keys())


def _audit(firm_id: str, req: dict, action: str, actor: dict, **extra) -> None:
    log_event(firm_id, "approval_request", req.get("id", ""), action,
              actor_id=actor.get("id"), actor_email=actor.get("email"),
              metadata={"request_type": req.get("request_type"), **extra})


# ── Public API ───────────────────────────────────────────────────────────────

def create_request(firm_id: str, request_type: str, payload: dict, actor: dict) -> dict:
    spec = _SPECS.get(request_type)
    if not spec:
        raise HTTPException(400, f"Unknown request_type '{request_type}'")
    missing = [k for k in spec["required"] if k not in (payload or {})]
    if missing:
        raise HTTPException(422, f"Missing payload fields: {', '.join(missing)}")
    row = approval_repo.create({
        "firm_id": firm_id, "request_type": request_type,
        "summary": spec["summary"](payload), "payload": payload,
        "status": "pending",
        "requested_by": actor.get("id"), "requested_by_email": actor.get("email"),
    })
    _audit(firm_id, row, "request_created", actor, summary=row.get("summary"))
    return row


def _load_pending(firm_id: str, request_id: str) -> dict:
    req = approval_repo.get(firm_id, request_id)
    if not req:
        raise HTTPException(404, "Approval request not found")
    if req["status"] != "pending":
        raise HTTPException(409, f"Request already {req['status']}")
    return req


def approve(firm_id: str, request_id: str, approver: dict) -> dict:
    req = _load_pending(firm_id, request_id)
    spec = _SPECS[req["request_type"]]
    result = spec["handler"](firm_id, req["payload"])  # executes the real mutation
    updated = approval_repo.update(firm_id, request_id, {
        "status": "approved", "decided_by": approver.get("id"),
        "decided_by_email": approver.get("email"), "decided_at": _now(), "result": result,
    })
    _audit(firm_id, req, "approved", approver)
    return updated


def reject(firm_id: str, request_id: str, approver: dict, reason: Optional[str] = None) -> dict:
    req = _load_pending(firm_id, request_id)
    updated = approval_repo.update(firm_id, request_id, {
        "status": "rejected", "decided_by": approver.get("id"),
        "decided_by_email": approver.get("email"), "decided_at": _now(), "reason": reason,
    })
    _audit(firm_id, req, "rejected", approver, reason=reason)
    return updated


def cancel(firm_id: str, request_id: str, actor: dict) -> dict:
    req = _load_pending(firm_id, request_id)
    # Only the original requester or a Partner may cancel a pending request.
    is_partner = str(actor.get("role", "")).strip().lower() in ("partner", "owner")
    if not is_partner and actor.get("id") != req.get("requested_by"):
        raise HTTPException(403, "Only the requester or a Partner may cancel this request")
    updated = approval_repo.update(firm_id, request_id, {
        "status": "cancelled", "decided_by": actor.get("id"),
        "decided_by_email": actor.get("email"), "decided_at": _now(),
    })
    _audit(firm_id, req, "cancelled", actor)
    return updated


def list_requests(firm_id: str, status: Optional[str] = None) -> list[dict]:
    return approval_repo.list(firm_id, status=status)


def get_request(firm_id: str, request_id: str) -> Optional[dict]:
    return approval_repo.get(firm_id, request_id)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
