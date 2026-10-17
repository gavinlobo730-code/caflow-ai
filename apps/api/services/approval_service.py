"""
Module 9.0 / M4 — Governance approval engine (maker-checker).

A maker submits an approval_request for a sensitive action; a Partner (checker)
approves or rejects. On approval the registered handler executes the real
mutation via existing repositories/services (no duplicated business logic). Every
transition is mirrored to the immutable audit_log.

Request types (handlers execute against existing server paths):
  user_create / user_activation / role_change        -> user_repo
  assignment_create / assignment_remove / assignment_transfer -> assignment_repo

The chart-of-accounts types (coa_create / coa_update / coa_delete) were RETIRED on 17-10-2026 (POST-A-007's review): their
handlers called the in-memory `domain.accounting_service`, which the REST routes had already been moved off because a change
made there "was reported as saved and was not", so an approved request recorded success and wrote no account. Nothing
creates one (no screen, no job). A stored request of a retired type can still be rejected or cancelled and is refused on
approval in words (`RETIRED_TYPES`).
"""
import logging
from typing import Optional

from fastapi import HTTPException

from repositories.approval_repository import approval_repo
from services.audit_service import log_event

_CANONICAL_ROLES = {"Partner", "Manager", "Executive", "Reviewer", "Client"}

logger = logging.getLogger(__name__)


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
    # firm_id scopes the write: p["user_id"] comes off a request payload, and a
    # Partner approving it must not be able to (de)activate another firm's user.
    return user_repo.update(p["user_id"], {"is_active": bool(p["is_active"])}, firm_id=firm_id) or {}


def _h_role_change(firm_id: str, p: dict) -> dict:
    from repositories.user_repository import user_repo
    if p.get("role") not in _CANONICAL_ROLES:
        raise HTTPException(400, "Invalid role")
    return user_repo.update(p["user_id"], {"role": p["role"]}, firm_id=firm_id) or {}


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
}

REQUEST_TYPES = tuple(_SPECS.keys())

# Types an earlier version accepted, that a stored row may still carry. Reading one is fine; carrying one out is not.
RETIRED_TYPES = frozenset({"coa_create", "coa_update", "coa_delete"})


def _audit(firm_id: str, req: dict, action: str, actor: dict, **extra) -> None:
    # `actor` is a current_user, and audit_log.actor_id takes the SUPABASE AUTH
    # id — the same key migration 111's trigger writes as auth.uid(). See
    # tests/test_the_audit_log_names_one_kind_of_actor.py.
    log_event(firm_id, "approval_request", req.get("id", ""), action,
              actor_id=actor.get("auth_user_id"), actor_email=actor.get("email"),
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


def _lost_the_race() -> HTTPException:
    return HTTPException(409, "Request already decided")


# A decision is CLAIMED before anything else happens: one `UPDATE ... WHERE status = 'pending'`
# (`approval_repo.decide_if_pending`), so of two simultaneous decisions exactly one gets a row back
# and the other is refused. Reading the status and writing it later left a window in which two
# approvals both passed the check and the handler (a user created, a role changed, an account
# archived) ran twice, and in which a rejection could overwrite an approval whose action had
# already run (POST-A-007).

def approve(firm_id: str, request_id: str, approver: dict) -> dict:
    req = _load_pending(firm_id, request_id)
    spec = _SPECS.get(req["request_type"])
    if spec is None:
        # Refused before the claim, so the request stays pending and can still be rejected or cancelled.
        raise HTTPException(409, "This kind of request can no longer be carried out. Reject it instead.")
    claimed = approval_repo.decide_if_pending(firm_id, request_id, {
        "status": "approved", "decided_by": approver.get("id"),
        "decided_by_email": approver.get("email"), "decided_at": _now(),
    })
    if claimed is None:
        raise _lost_the_race()
    try:
        result = spec["handler"](firm_id, req["payload"])  # executes the real mutation
    except Exception:
        # The action raised, so the request is not decided: put it back for the next try. A handler is one repository
        # call or two (the same as before the claim existed, when a failure also left the request pending), so the
        # retry is the same attempt again. If even the put-back fails, or the process dies between the claim and the
        # result, the request is left reading approved with no result: the API refuses a second approval of it (409),
        # and the log says so at ERROR in the first case.
        try:
            approval_repo.update(firm_id, request_id, {
                "status": "pending", "decided_by": None, "decided_by_email": None, "decided_at": None,
            })
        except Exception:  # noqa: BLE001 - the original failure is the one to raise
            logger.error("approval %s: the action failed AND the request could not be put back to pending",
                         request_id, exc_info=True)
        raise
    updated = approval_repo.update(firm_id, request_id, {"result": result})
    _audit(firm_id, req, "approved", approver)
    return updated


def reject(firm_id: str, request_id: str, approver: dict, reason: Optional[str] = None) -> dict:
    req = _load_pending(firm_id, request_id)
    updated = approval_repo.decide_if_pending(firm_id, request_id, {
        "status": "rejected", "decided_by": approver.get("id"),
        "decided_by_email": approver.get("email"), "decided_at": _now(), "reason": reason,
    })
    if updated is None:
        raise _lost_the_race()
    _audit(firm_id, req, "rejected", approver, reason=reason)
    return updated


def cancel(firm_id: str, request_id: str, actor: dict) -> dict:
    req = _load_pending(firm_id, request_id)
    # Only the original requester or a Partner may cancel a pending request.
    is_partner = str(actor.get("role", "")).strip().lower() in ("partner", "owner")
    if not is_partner and actor.get("id") != req.get("requested_by"):
        raise HTTPException(403, "Only the requester or a Partner may cancel this request")
    updated = approval_repo.decide_if_pending(firm_id, request_id, {
        "status": "cancelled", "decided_by": actor.get("id"),
        "decided_by_email": actor.get("email"), "decided_at": _now(),
    })
    if updated is None:
        raise _lost_the_race()
    _audit(firm_id, req, "cancelled", actor)
    return updated


def list_requests(firm_id: str, status: Optional[str] = None) -> list[dict]:
    return approval_repo.list(firm_id, status=status)


def get_request(firm_id: str, request_id: str) -> Optional[dict]:
    return approval_repo.get(firm_id, request_id)


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()
